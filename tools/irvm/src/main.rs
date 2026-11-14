// silu-irvm: an IR -> bytecode compiler + compact stack VM for the
// Silu int-only IR subset, following monty's bytecode conventions
// (stack-based execution, u8 opcode discriminants with operand
// suffixes, a const pool, named locals as frame slots, jump-based
// control flow).
//
// Pipeline: silu_fe emits the IR JSON on stdin -> this tool compiles it
// to a byte stream (loud bail outside the int-only subset, matching
// selfhost/ir_interp.si's whitelist) -> executes -> prints the program
// output. The byte stream layout is fixed, so the Silu twin
// (selfhost/ir_vm.si) can produce byte-identical streams for the same
// IR - the two planes are cross-checked by tools/irvm/bytecode_diff.sh.

use std::collections::HashMap;
use std::io::{self, Read, Write};

// ---------------- opcodes (monty-style: u8 discriminant + operands) ---
// operand suffixes: W = one u16 LE, K = one u8, none = pure stack op
const OP_LOAD_CONST: u8 = 0x01; // W: const pool index
const OP_LOAD_LOCAL: u8 = 0x02; // W: frame slot
const OP_STORE_LOCAL: u8 = 0x03; // W: frame slot
const OP_ADD: u8 = 0x04; // pop b, pop a -> push a+b
const OP_SUB: u8 = 0x05;
const OP_MUL: u8 = 0x06;
const OP_FLOORDIV: u8 = 0x07; // div-zero traps loudly
const OP_MOD: u8 = 0x08;
const OP_POW: u8 = 0x09; // exp by squaring; negative exp -> 0
const OP_CMP_EQ: u8 = 0x0a; // push 1/0
const OP_CMP_NE: u8 = 0x0b;
const OP_CMP_LT: u8 = 0x0c;
const OP_CMP_LE: u8 = 0x0d;
const OP_CMP_GT: u8 = 0x0e;
const OP_CMP_GE: u8 = 0x0f;
const OP_JUMP: u8 = 0x10; // W: absolute target
const OP_JUMP_IF_FALSE: u8 = 0x11; // W: target (pop cond)
const OP_CALL: u8 = 0x12; // K: argc, W: func idx (args pushed in order)
const OP_RETURN: u8 = 0x13; // pop -> frame return value
const OP_PRINT: u8 = 0x14; // K: argc - pop argc, space-join + newline
const OP_POP: u8 = 0x15; // discard
const OP_LOAD_INT0: u8 = 0x16; // push 0
const OP_LOAD_INT1: u8 = 0x17; // push 1

// ---------------- IR JSON reader --------------------------------------
#[derive(Clone, Debug)]
enum J {
    Arr(Vec<J>),
    Str(String),
    Num(f64),
    Bool(bool),
    Null,
}

impl J {
    fn arr(&self) -> &[J] {
        match self {
            J::Arr(v) => v,
            _ => &[],
        }
    }
    fn s(&self) -> &str {
        match self {
            J::Str(s) => s,
            _ => "",
        }
    }
    fn n(&self) -> i64 {
        match self {
            J::Num(f) => *f as i64,
            J::Bool(b) => *b as i64,
            _ => 0,
        }
    }
}

struct JsonReader<'a> {
    src: &'a [u8],
    pos: usize,
}

impl<'a> JsonReader<'a> {
    fn ws(&mut self) {
        while self.pos < self.src.len() {
            match self.src[self.pos] {
                b' ' | b'\n' | b'\t' | b'\r' => self.pos += 1,
                _ => break,
            }
        }
    }

    fn value(&mut self) -> Result<J, String> {
        self.ws();
        if self.pos >= self.src.len() {
            return Err("unexpected end of json".into());
        }
        match self.src[self.pos] {
            b'[' => self.array(),
            b'"' => Ok(J::Str(self.string()?)),
            b't' => {
                self.pos += 4;
                Ok(J::Bool(true))
            }
            b'f' => {
                self.pos += 5;
                Ok(J::Bool(false))
            }
            b'n' => {
                self.pos += 4;
                Ok(J::Null)
            }
            b'-' | b'0'..=b'9' => self.number(),
            c => Err(format!(
                "unexpected json char '{}' at {}",
                c as char, self.pos
            )),
        }
    }

    fn array(&mut self) -> Result<J, String> {
        self.pos += 1;
        let mut items = Vec::new();
        loop {
            self.ws();
            if self.pos >= self.src.len() {
                return Err("unterminated json array".into());
            }
            if self.src[self.pos] == b']' {
                self.pos += 1;
                return Ok(J::Arr(items));
            }
            items.push(self.value()?);
            self.ws();
            if self.pos < self.src.len() && self.src[self.pos] == b',' {
                self.pos += 1;
            }
        }
    }

    fn string(&mut self) -> Result<String, String> {
        self.pos += 1;
        let start = self.pos;
        while self.pos < self.src.len() {
            match self.src[self.pos] {
                b'"' => {
                    let out =
                        String::from_utf8_lossy(&self.src[start..self.pos]).into_owned();
                    self.pos += 1;
                    return Ok(out);
                }
                b'\\' => self.pos += 2,
                _ => self.pos += 1,
            }
        }
        Err("unterminated json string".into())
    }

    fn number(&mut self) -> Result<J, String> {
        let start = self.pos;
        let mut isf = false;
        if self.src[self.pos] == b'-' {
            self.pos += 1;
        }
        while self.pos < self.src.len() {
            match self.src[self.pos] {
                b'0'..=b'9' => self.pos += 1,
                b'.' | b'e' | b'E' => {
                    isf = true;
                    self.pos += 1;
                }
                b'+' | b'-' => {
                    let prev = self.src[self.pos - 1];
                    if prev == b'e' || prev == b'E' {
                        self.pos += 1;
                    } else {
                        break;
                    }
                }
                _ => break,
            }
        }
        if self.pos == start || (self.pos == start + 1 && self.src[start] == b'-') {
            return Err(format!("bad json number at {}", start));
        }
        let text = std::str::from_utf8(&self.src[start..self.pos]).unwrap();
        if isf {
            Ok(J::Num(text.parse::<f64>().unwrap_or(0.0)))
        } else {
            Ok(J::Num(text.parse::<i64>().unwrap_or(0) as f64))
        }
    }
}

// ---------------- bytecode builder with label patching ----------------
struct CodeBuilder {
    bytes: Vec<u8>,
    patches: Vec<(usize, usize)>,
    labels: HashMap<usize, usize>,
}

impl CodeBuilder {
    fn here(&self) -> usize {
        self.bytes.len()
    }
    fn label(&mut self, id: usize) {
        self.labels.insert(id, self.bytes.len());
        self.patch();
    }
    fn op(&mut self, op: u8) {
        self.bytes.push(op);
    }
    fn op_w(&mut self, op: u8, w: u16) {
        self.bytes.push(op);
        self.bytes.extend_from_slice(&w.to_le_bytes());
    }
    fn op_kw(&mut self, op: u8, k: u8, w: u16) {
        self.bytes.push(op);
        self.bytes.push(k);
        self.bytes.extend_from_slice(&w.to_le_bytes());
    }
    fn op_k(&mut self, op: u8, k: u8) {
        self.bytes.push(op);
        self.bytes.push(k);
    }
    fn jump(&mut self, op: u8, label: usize) {
        self.bytes.push(op);
        self.patches.push((self.bytes.len(), label));
        self.bytes.extend_from_slice(&[0, 0]);
    }
    // raw jump: the operand position is returned for DIRECT patching
    // (break/continue know their exact targets at loop tail time)
    fn jump_raw(&mut self, op: u8) -> usize {
        self.bytes.push(op);
        let pos = self.bytes.len();
        self.bytes.extend_from_slice(&[0, 0]);
        pos
    }
    fn patch_at(&mut self, pos: usize, target: usize) {
        let t = target as u16;
        self.bytes[pos] = (t & 0xff) as u8;
        self.bytes[pos + 1] = (t >> 8) as u8;
    }
    fn patch(&mut self) {
        let pending = std::mem::take(&mut self.patches);
        for (pos, label) in pending {
            match self.labels.get(&label) {
                Some(&target) => self.patch_at(pos, target),
                None => self.patches.push((pos, label)),
            }
        }
    }
}

// ---------------- program model --------------------------------------
#[derive(Clone)]
struct FuncMeta {
    name: String,
    params: usize,
    nslots: usize,
    start: usize,
    len: usize,
}

struct Program {
    consts: Vec<i64>,
    funcs: Vec<FuncMeta>,
    code: Vec<u8>,
    module_slots: usize,
    module_len: usize,
}

// ---------------- IR -> bytecode compiler ----------------------------
struct Compiler {
    consts: Vec<i64>,
    const_map: HashMap<i64, u16>,
    func_idx: HashMap<String, usize>,
    funcs: Vec<FuncMeta>,
    code: CodeBuilder,
    locals: HashMap<String, usize>,
    nlocals: usize,
    breaks: Vec<Vec<usize>>,
    continues: Vec<Vec<usize>>,
    next_label: usize,
    error: Option<String>,
}

impl Compiler {
    fn new() -> Self {
        Compiler {
            consts: Vec::new(),
            const_map: HashMap::new(),
            func_idx: HashMap::new(),
            funcs: Vec::new(),
            code: CodeBuilder {
                bytes: Vec::new(),
                patches: Vec::new(),
                labels: HashMap::new(),
            },
            locals: HashMap::new(),
            nlocals: 0,
            breaks: Vec::new(),
            continues: Vec::new(),
            next_label: 0,
            error: None,
        }
    }

    fn bail(&mut self, msg: String) {
        if self.error.is_none() {
            self.error = Some(msg);
        }
    }

    fn label(&mut self) -> usize {
        self.next_label += 1;
        self.next_label
    }

    fn const_idx(&mut self, v: i64) -> u16 {
        if let Some(i) = self.const_map.get(&v) {
            return *i;
        }
        let idx = self.consts.len() as u16;
        self.consts.push(v);
        self.const_map.insert(v, idx);
        idx
    }

    fn slot(&mut self, name: &str) -> usize {
        if let Some(i) = self.locals.get(name) {
            return *i;
        }
        let i = self.nlocals;
        self.nlocals += 1;
        self.locals.insert(name.to_string(), i);
        i
    }

    // pass A: function names first (forward calls), program order
    fn collect_funcs(&mut self, stmts: &J) {
        for st in stmts.arr() {
            let items = st.arr();
            match items.first().map(|j| j.s()) {
                Some("func_def") => {
                    let name = items[1].s().to_string();
                    if !self.func_idx.contains_key(&name) {
                        self.func_idx.insert(name, self.funcs.len());
                        self.funcs.push(FuncMeta {
                            name: items[1].s().to_string(),
                            params: items[2].arr().len(),
                            nslots: 0,
                            start: 0,
                            len: 0,
                        });
                    }
                    self.collect_funcs(&items[3]);
                }
                Some("if") => {
                    self.collect_funcs(&items[2]);
                    self.collect_funcs(&items[3]);
                }
                Some("while") => self.collect_funcs(&items[2]),
                _ => {}
            }
        }
    }

    // expressions: push exactly one value; Err means the error is
    // already recorded
    fn emit_expr(&mut self, node: &J) -> Result<(), ()> {
        let items = node.arr();
        let t = items.first().map(|j| j.s()).unwrap_or("");
        match t {
            "const" => {
                let v = items[1].n();
                match v {
                    0 => self.code.op(OP_LOAD_INT0),
                    1 => self.code.op(OP_LOAD_INT1),
                    _ => {
                        let ci = self.const_idx(v);
                        self.code.op_w(OP_LOAD_CONST, ci);
                    }
                }
                Ok(())
            }
            "name" => {
                let name = items[1].s().to_string();
                match self.locals.get(&name) {
                    Some(&slot) => {
                        self.code.op_w(OP_LOAD_LOCAL, slot as u16);
                        Ok(())
                    }
                    None => {
                        self.bail(format!("unknown variable '{}'", name));
                        Err(())
                    }
                }
            }
            "-" if items.len() == 2 => {
                // unary minus: the FE emits ["-", x] for -x; emit 0 - x
                self.code.op(OP_LOAD_INT0);
                self.emit_expr(&items[1])?;
                self.code.op(OP_SUB);
                Ok(())
            }
            "+" | "-" | "*" | "//" | "%" | "**" | "<" | "<=" | ">" | ">="
            | "==" | "!=" => {
                self.emit_expr(&items[1])?;
                self.emit_expr(&items[2])?;
                let op = match t {
                    "+" => OP_ADD,
                    "-" => OP_SUB,
                    "*" => OP_MUL,
                    "//" => OP_FLOORDIV,
                    "%" => OP_MOD,
                    "**" => OP_POW,
                    "==" => OP_CMP_EQ,
                    "!=" => OP_CMP_NE,
                    "<" => OP_CMP_LT,
                    "<=" => OP_CMP_LE,
                    ">" => OP_CMP_GT,
                    _ => OP_CMP_GE,
                };
                self.code.op(op);
                Ok(())
            }
            "and" | "or" => {
                // flat operand lists, short-circuit chains; result 0/1
                // (matching ir_interp's documented and/or semantics)
                let end = self.label();
                let n = items.len();
                for (i, operand) in items.iter().enumerate().skip(1) {
                    self.emit_expr(operand)?;
                    if i < n - 1 {
                        let skip = self.label();
                        if t == "and" {
                            self.code.jump(OP_JUMP_IF_FALSE, end);
                            self.code.op(OP_POP);
                        } else {
                            self.code.jump(OP_JUMP_IF_FALSE, skip);
                            self.code.op(OP_POP);
                            self.code.op(OP_LOAD_INT1);
                            self.code.jump(OP_JUMP, end);
                            self.code.label(skip);
                            self.code.op(OP_POP);
                        }
                    } else {
                        let zero = self.label();
                        self.code.jump(OP_JUMP_IF_FALSE, zero);
                        self.code.op(OP_LOAD_INT1);
                        self.code.jump(OP_JUMP, end);
                        self.code.label(zero);
                        self.code.op(OP_POP);
                        self.code.op(OP_LOAD_INT0);
                    }
                }
                self.code.label(end);
                Ok(())
            }
            "not" => {
                self.emit_expr(&items[1])?;
                let zero = self.label();
                let end = self.label();
                self.code.jump(OP_JUMP_IF_FALSE, zero);
                self.code.op(OP_LOAD_INT0);
                self.code.jump(OP_JUMP, end);
                self.code.label(zero);
                self.code.op(OP_POP);
                self.code.op(OP_LOAD_INT1);
                self.code.label(end);
                Ok(())
            }
            "call" => {
                let callee = &items[1];
                if callee.arr().first().map(|j| j.s()) != Some("name") {
                    self.bail("call with non-name callee".into());
                    return Err(());
                }
                let name = callee.arr()[1].s().to_string();
                // print is a builtin call in the IR: emit every arg,
                // then OP_PRINT with the arg count (the VM renders
                // space-joined values + newline). Checked BEFORE the
                // user function lookup - print is not in func_idx.
                if name == "print" {
                    let args = &items[2];
                    if args.arr().len() > 255 {
                        self.bail("print with more than 255 args".into());
                        return Err(());
                    }
                    for a in args.arr() {
                        self.emit_expr(a)?;
                    }
                    self.code.op_k(OP_PRINT, args.arr().len() as u8);
                    return Ok(());
                }
                let idx = match self.func_idx.get(&name) {
                    Some(i) => *i,
                    None => {
                        self.bail(format!(
                            "call to unsupported builtin '{}'",
                            name
                        ));
                        return Err(());
                    }
                };
                let args = &items[2];
                if args.arr().len() > 255 {
                    self.bail("call with more than 255 args".into());
                    return Err(());
                }
                for a in args.arr() {
                    self.emit_expr(a)?;
                }
                self.code
                    .op_kw(OP_CALL, args.arr().len() as u8, idx as u16);
                Ok(())
            }
            other => {
                self.bail(format!("unsupported expression '{}'", other));
                Err(())
            }
        }
    }

    // statements: Err means the error is already recorded
    fn emit_stmt(&mut self, stmt: &J) -> Result<(), ()> {
        let items = stmt.arr();
        let t = items.first().map(|j| j.s()).unwrap_or("");
        match t {
            "line" => Ok(()),
            "assign" | "ann_assign" => {
                self.emit_expr(&items[2])?;
                let slot = self.slot(items[1].s());
                self.code.op_w(OP_STORE_LOCAL, slot as u16);
                Ok(())
            }
            "aug_assign" => {
                let name = items[1].arr()[1].s().to_string();
                let op_str = items[2].s().to_string();
                match self.locals.get(&name) {
                    Some(&slot) => {
                        self.code.op_w(OP_LOAD_LOCAL, slot as u16);
                        self.emit_expr(&items[3])?;
                        let op = match op_str.as_str() {
                            "+=" => OP_ADD,
                            "-=" => OP_SUB,
                            "*=" => OP_MUL,
                            "//=" => OP_FLOORDIV,
                            "%=" => OP_MOD,
                            "**=" => OP_POW,
                            other => {
                                self.bail(format!(
                                    "unsupported aug op '{}'",
                                    other
                                ));
                                return Err(());
                            }
                        };
                        self.code.op(op);
                        self.code.op_w(OP_STORE_LOCAL, slot as u16);
                        Ok(())
                    }
                    None => {
                        self.bail(format!(
                            "aug_assign on unknown variable '{}'",
                            name
                        ));
                        Err(())
                    }
                }
            }
            "print" => {
                self.emit_expr(&items[1])?;
                self.code.op_k(OP_PRINT, 1);
                Ok(())
            }
            "call" => {
                self.emit_expr(stmt)?;
                self.code.op(OP_POP);
                Ok(())
            }
            "func_def" => Ok(()), // compiled separately in pass B
            "return" => {
                self.emit_expr(&items[1])?;
                self.code.op(OP_RETURN);
                Ok(())
            }
            "break" => {
                match self.breaks.last_mut() {
                    Some(list) => {
                        let pos = self.code.jump_raw(OP_JUMP);
                        list.push(pos);
                        Ok(())
                    }
                    None => {
                        self.bail("break outside a loop".into());
                        Err(())
                    }
                }
            }
            "continue" => {
                match self.continues.last_mut() {
                    Some(list) => {
                        let pos = self.code.jump_raw(OP_JUMP);
                        list.push(pos);
                        Ok(())
                    }
                    None => {
                        self.bail("continue outside a loop".into());
                        Err(())
                    }
                }
            }
            "if" => {
                self.emit_expr(&items[1])?;
                let else_l = self.label();
                let end_l = self.label();
                self.code.jump(OP_JUMP_IF_FALSE, else_l);
                self.emit_block(&items[2])?;
                self.code.jump(OP_JUMP, end_l);
                self.code.label(else_l);
                self.emit_block(&items[3])?;
                self.code.label(end_l);
                Ok(())
            }
            "while" => {
                let top = self.label();
                let end = self.label();
                self.code.label(top);
                self.emit_expr(&items[1])?;
                self.code.jump(OP_JUMP_IF_FALSE, end);
                self.breaks.push(Vec::new());
                self.continues.push(Vec::new());
                self.emit_block(&items[2])?;
                // continue sites jump back to the condition
                let top_off = self.code.labels[&top];
                let conts = self.continues.pop().unwrap();
                for pos in conts {
                    self.code.patch_at(pos, top_off);
                }
                self.code.jump(OP_JUMP, top);
                self.code.label(end);
                // break sites jump past the whole loop
                let end_off = self.code.labels[&end];
                let brs = self.breaks.pop().unwrap();
                for pos in brs {
                    self.code.patch_at(pos, end_off);
                }
                Ok(())
            }
            other => {
                self.bail(format!("unsupported statement '{}'", other));
                Err(())
            }
        }
    }

    fn emit_block(&mut self, stmts: &J) -> Result<(), ()> {
        for st in stmts.arr() {
            self.emit_stmt(st)?;
        }
        Ok(())
    }
}

// ---------------- VM --------------------------------------------------
struct Frame {
    slots: Vec<i64>,
    pc: usize,
    end: usize,
    base: usize, // value-stack depth at entry
}

struct Vm<'p> {
    prog: &'p Program,
    stack: Vec<i64>,
    frames: Vec<Frame>,
    out: String,
}

impl<'p> Vm<'p> {
    fn run(&mut self) -> Result<(), String> {
        self.frames.push(Frame {
            slots: vec![0; self.prog.module_slots.max(1)],
            pc: 0,
            end: self.prog.module_len,
            base: 0,
        });
        loop {
            if self.frames.is_empty() {
                return Ok(());
            }
            let frame = self.frames.last().unwrap();
            if frame.pc >= frame.end {
                // fell off the region end: implicit return 0
                let ret = 0i64;
                self.frames.pop();
                if self.frames.is_empty() {
                    return Ok(());
                }
                let base = self.frames.last().unwrap().base;
                self.stack.truncate(base);
                self.stack.push(ret);
                continue;
            }
            let code = &self.prog.code;
            let (fpc, fbase, fend, fslots, fdepth, op, stack_dbg) =
                if std::env::var("IRVM_TRACE").is_ok() {
                    let f = self.frames.last().unwrap();
                    (
                        f.pc,
                        f.base,
                        f.end,
                        Some(f.slots.clone()),
                        self.frames.len(),
                        code[f.pc],
                        Some(self.stack.clone()),
                    )
                } else {
                    let f = self.frames.last().unwrap();
                    (f.pc, f.base, f.end, None, self.frames.len(), code[f.pc], None)
                };
            if let Some(st) = stack_dbg {
                eprintln!(
                    "pc={} base={} end={} stack={:?} slots={:?} frames={}",
                    fpc, fbase, fend, st, fslots, fdepth
                );
            }
            let frame = self.frames.last_mut().unwrap();
            frame.pc = fpc + 1;
            match op {
                OP_LOAD_CONST => {
                    let idx = read_w(code, &mut frame.pc) as usize;
                    let v = *self.prog.consts.get(idx).unwrap_or(&0);
                    self.stack.push(v);
                }
                OP_LOAD_LOCAL => {
                    let slot = read_w(code, &mut frame.pc) as usize;
                    let v = *frame.slots.get(slot).unwrap_or(&0);
                    self.stack.push(v);
                }
                OP_STORE_LOCAL => {
                    let slot = read_w(code, &mut frame.pc) as usize;
                    let v = self.stack.pop().unwrap_or(0);
                    if slot < frame.slots.len() {
                        frame.slots[slot] = v;
                    }
                }
                OP_ADD | OP_SUB | OP_MUL | OP_FLOORDIV | OP_MOD | OP_POW => {
                    let b = self.stack.pop().unwrap_or(0);
                    let a = self.stack.pop().unwrap_or(0);
                    let v = match op {
                        OP_ADD => a.wrapping_add(b),
                        OP_SUB => a.wrapping_sub(b),
                        OP_MUL => a.wrapping_mul(b),
                        OP_FLOORDIV => {
                            if b == 0 {
                                return Err("division by zero".into());
                            }
                            a.wrapping_div(b)
                        }
                        OP_MOD => {
                            if b == 0 {
                                return Err("modulo by zero".into());
                            }
                            a.wrapping_rem(b)
                        }
                        _ => {
                            // negative exponent -> the documented
                            // silent-0 (matches ir_interp)
                            if b < 0 {
                                0
                            } else {
                                ipow(a, b)
                            }
                        }
                    };
                    self.stack.push(v);
                }
                OP_CMP_EQ | OP_CMP_NE | OP_CMP_LT | OP_CMP_LE | OP_CMP_GT
                | OP_CMP_GE => {
                    let b = self.stack.pop().unwrap_or(0);
                    let a = self.stack.pop().unwrap_or(0);
                    let v = match op {
                        OP_CMP_EQ => a == b,
                        OP_CMP_NE => a != b,
                        OP_CMP_LT => a < b,
                        OP_CMP_LE => a <= b,
                        OP_CMP_GT => a > b,
                        _ => a >= b,
                    };
                    self.stack.push(if v { 1 } else { 0 });
                }
                OP_JUMP => {
                    let target = read_w(code, &mut frame.pc) as usize;
                    frame.pc = target;
                }
                OP_JUMP_IF_FALSE => {
                    let target = read_w(code, &mut frame.pc) as usize;
                    let v = self.stack.pop().unwrap_or(0);
                    if v == 0 {
                        frame.pc = target;
                    }
                }
                OP_CALL => {
                    let argc = code[frame.pc] as usize;
                    frame.pc += 1;
                    let fidx = read_w(code, &mut frame.pc) as usize;
                    let meta = match self.prog.funcs.get(fidx) {
                        Some(m) => (m.start, m.start + m.len, m.nslots),
                        None => return Err("call to unknown function".into()),
                    };
                    if self.stack.len() < argc {
                        return Err("stack underflow at call".into());
                    }
                    let arg_start = self.stack.len() - argc;
                    let mut slots = vec![0i64; meta.2.max(argc)];
                    for (i, a) in self.stack[arg_start..].iter().enumerate() {
                        slots[i] = *a;
                    }
                    self.stack.truncate(arg_start);
                    self.frames.push(Frame {
                        slots,
                        pc: meta.0,
                        end: meta.1,
                        base: self.stack.len(),
                    });
                }
                OP_RETURN => {
                    let ret = self.stack.pop().unwrap_or(0);
                    // restore the stack to the depth AT THE CALL: the
                    // returning frame's own base (= the caller's depth
                    // after the args were moved into the frame slots).
                    // Using the CALLER's base here (frames.last() after
                    // the pop) wipes the caller's pending values - e.g.
                    // fib(n-1)'s result waiting for the ADD in
                    // fib(n-1) + fib(n-2) - and every fib(n) silently
                    // became fib(n-2).
                    let base = frame.base;
                    self.frames.pop();
                    if self.frames.is_empty() {
                        return Ok(());
                    }
                    self.stack.truncate(base);
                    self.stack.push(ret);
                }
                OP_PRINT => {
                    let argc = code[frame.pc] as usize;
                    frame.pc += 1;
                    if self.stack.len() < argc {
                        return Err("stack underflow at print".into());
                    }
                    let start = self.stack.len() - argc;
                    for (i, v) in self.stack[start..].iter().enumerate() {
                        if i > 0 {
                            self.out.push(' ');
                        }
                        self.out.push_str(&v.to_string());
                    }
                    self.out.push('\n');
                    self.stack.truncate(start);
                }
                OP_POP => {
                    self.stack.pop();
                }
                OP_LOAD_INT0 => self.stack.push(0),
                OP_LOAD_INT1 => self.stack.push(1),
                _ => return Err(format!("unknown opcode {:#x}", op)),
            }
        }
    }
}

fn read_w(code: &[u8], pc: &mut usize) -> u16 {
    let lo = code[*pc] as u16;
    let hi = code[*pc + 1] as u16;
    *pc += 2;
    lo | (hi << 8)
}

fn ipow(mut base: i64, mut e: i64) -> i64 {
    let mut r: i64 = 1;
    while e > 0 {
        if e % 2 == 1 {
            r = r.wrapping_mul(base);
        }
        e /= 2;
        if e > 0 {
            base = base.wrapping_mul(base);
        }
    }
    r
}

// ---------------- program assembly ------------------------------------
// layout: [module code][function bodies in program order]. The module
// frame's slots hold module-level names; each function body gets a
// fresh locals map with params at slots 0..argc (the Call op fills
// them from the value stack).
fn assemble(comp: &mut Compiler, module_stmts: &J) -> Result<Program, String> {
    comp.collect_funcs(module_stmts);
    let module_len;
    let module_slots;
    if comp.emit_block(module_stmts).is_err() {
        return Err(comp.error.clone().unwrap_or_else(|| "compile error".into()));
    }
    comp.code.patch();
    module_len = comp.code.here();
    module_slots = comp.nlocals.max(1);

    // function bodies: fresh locals per body, params at slots 0..argc
    let defs = find_func_defs(module_stmts);
    let mut func_list = std::mem::take(&mut comp.funcs);
    for f in func_list.iter_mut() {
        comp.locals.clear();
        comp.nlocals = 0;
        let def = match defs.iter().find(|d| d.0 == f.name) {
            Some(d) => d,
            None => continue,
        };
        for p in def.1.arr() {
            comp.slot(p.s());
        }
        f.start = comp.code.here();
        if comp.emit_block(&def.2).is_err() {
            return Err(comp.error.clone().unwrap_or_else(|| "compile error".into()));
        }
        comp.code.patch();
        f.len = comp.code.here() - f.start;
        f.nslots = comp.nlocals.max(f.params);
    }
    comp.funcs = func_list;
    Ok(Program {
        consts: comp.consts.clone(),
        funcs: comp.funcs.clone(),
        code: comp.code.bytes.clone(),
        module_slots,
        module_len,
    })
}

// (name, params J, body J) for every func_def in program order
fn find_func_defs(stmts: &J) -> Vec<(String, J, J)> {
    let mut out = Vec::new();
    for st in stmts.arr() {
        let items = st.arr();
        match items.first().map(|j| j.s()) {
            Some("func_def") => {
                out.push((
                    items[1].s().to_string(),
                    items[2].clone(),
                    items[3].clone(),
                ));
                out.extend(find_func_defs(&items[3]));
            }
            Some("if") => {
                out.extend(find_func_defs(&items[2]));
                out.extend(find_func_defs(&items[3]));
            }
            Some("while") => out.extend(find_func_defs(&items[2])),
            _ => {}
        }
    }
    out
}

// ---------------- main ------------------------------------------------
fn main() {
    let mut input = Vec::new();
    if io::stdin().read_to_end(&mut input).is_err() {
        eprintln!("irvm bail: cannot read stdin");
        std::process::exit(3);
    }
    let mut reader = JsonReader { src: &input, pos: 0 };
    let root = match reader.value() {
        Ok(r) => r,
        Err(e) => {
            eprintln!("irvm bail: {}", e);
            std::process::exit(3);
        }
    };
    if root.arr().first().map(|j| j.s()) != Some("module") {
        eprintln!("irvm bail: not an IR module");
        std::process::exit(3);
    }
    let body = root.arr()[1].clone();
    let mut comp = Compiler::new();
    let prog = match assemble(&mut comp, &body) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("irvm bail: {}", e);
            std::process::exit(3);
        }
    };
    // --dump-bytecode: emit the compiled byte stream as hex (one line)
    // and exit - the cross-plane check (tools/irvm/bytecode_diff.sh)
    // diffs this against the Silu twin's stream for the same IR
    if std::env::var("IRVM_DUMP").is_ok() {
        for b in &prog.code {
            print!("{:02x}", b);
        }
        println!();
        return;
    }
    let mut vm = Vm {
        prog: &prog,
        stack: Vec::new(),
        frames: Vec::new(),
        out: String::new(),
    };
    match vm.run() {
        Ok(()) => {
            io::stdout().write_all(vm.out.as_bytes()).ok();
        }
        Err(e) => {
            // partial output is discarded - loud failure only
            eprintln!("irvm bail: {}", e);
            std::process::exit(3);
        }
    }
}
