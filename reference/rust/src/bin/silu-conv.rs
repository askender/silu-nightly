// silu-conv: R2 - typed converter for the pinned snapshot (silu 1.16.2
// / 87df40f). Reads a .si path, gets IR JSON from the verified silu-fe
// sibling, emits const_prefix.ll + user functions + main + tail
// globals. Constructs outside the implemented subset exit 3 (harness
// reports ERROR, never wrong bytes).
//
// Architecture: FnBuilder holds a block LIST in creation order (the
// output order) with a current-block cursor; every instruction
// consumes one anon slot (void ones silently); panic pairs create
// panic_bad/panic_ok blocks and the continuation flows inside
// panic_ok - the arith discovery.

use std::cell::RefCell;
use std::env;
use std::io::Write;
use std::process::Command;

const CONST_PREFIX: &str = include_str!("../../const_prefix.ll");
const STR_BASE: usize = 297; // runtime consumed 0..=296 (see README)

#[derive(Clone, Debug, PartialEq)]
enum Val { Null, Bool(bool), Int(i64), Float(f64), Str(String), List(Vec<Val>) }

impl Val {
    fn head(&self) -> &str {
        match self { Val::List(v) => match &v[0] { Val::Str(s) => s, _ => "" }, _ => "" }
    }
    fn get(&self, k: usize) -> Val {
        match self { Val::List(v) => v.get(k).cloned().unwrap_or(Val::Null), _ => Val::Null }
    }
    fn items(&self) -> Vec<Val> { match self { Val::List(v) => v.clone(), _ => vec![] } }
    fn str_of(&self) -> String { match self { Val::Str(s) => s.clone(), _ => String::new() }
    }
    fn int_of(&self) -> i64 { match self { Val::Int(i) => *i, _ => 0 } }
}

fn parse_json(s: &str) -> Val {
    let b: Vec<char> = s.chars().collect();
    let mut i = 0usize;
    pj(&b, &mut i)
}

fn pj(b: &[char], i: &mut usize) -> Val {
    while *i < b.len() && b[*i].is_whitespace() { *i += 1; }
    match b[*i] {
        'n' => { *i += 4; Val::Null }
        't' => { *i += 4; Val::Bool(true) }
        'f' => { *i += 5; Val::Bool(false) }
        '"' => {
            *i += 1;
            let mut out = String::new();
            while b[*i] != '"' {
                if b[*i] == '\\' {
                    *i += 1;
                    match b[*i] {
                        'n' => out.push('\n'), 't' => out.push('\t'),
                        'r' => out.push('\r'),
                        'u' => {
                            let h: String = b[*i + 1..*i + 5].iter().collect();
                            let cp = u32::from_str_radix(&h, 16).unwrap_or(0);
                            out.push(char::from_u32(cp).unwrap_or('\u{fffd}'));
                            *i += 4;
                        }
                        c => out.push(c),
                    }
                } else { out.push(b[*i]); }
                *i += 1;
            }
            *i += 1;
            Val::Str(out)
        }
        '[' => {
            *i += 1;
            let mut items = Vec::new();
            loop {
                while *i < b.len() && b[*i].is_whitespace() { *i += 1; }
                if b[*i] == ']' { *i += 1; break; }
                items.push(pj(b, i));
                while *i < b.len() && b[*i].is_whitespace() { *i += 1; }
                if b[*i] == ',' { *i += 1; }
            }
            Val::List(items)
        }
        _ => {
            let start = *i;
            while *i < b.len() && (b[*i].is_ascii_digit() || "+-.eE".contains(b[*i])) {
                *i += 1;
            }
            let t: String = b[start..*i].iter().collect();
            if t.contains('.') || t.contains('e') || t.contains('E') {
                Val::Float(t.parse().unwrap_or(0.0))
            } else {
                Val::Int(t.parse().unwrap_or(0))
            }
        }
    }
}

fn bail(what: &str) -> ! {
    eprintln!("silu-conv: unsupported in R2 milestone: {}", what);
    std::process::exit(3);
}

fn escape_bytes(data: &[u8]) -> String {
    const PUNCT: &str = " !#$%&'()*+,-./:;<=>?@[]^_`{|}~";
    let mut out = String::new();
    for &b in data {
        if b.is_ascii_alphanumeric() || PUNCT.as_bytes().contains(&b) {
            out.push(b as char);
        } else {
            out.push('\\');
            out.push_str(&format!("{:02x}", b));
        }
    }
    out
}

thread_local! {
    // tail globals in strict CREATION order: strings and module var
    // declarations interleave as they are first emitted (list.si find)
    static TAIL: RefCell<Vec<String>> = RefCell::new(Vec::new());
    static STR_SLOTS: RefCell<Vec<String>> = RefCell::new(Vec::new());
    static LST_SLOTS: RefCell<Vec<String>> = RefCell::new(Vec::new()); // list-typed globals
    static DCT_SLOTS: RefCell<Vec<String>> = RefCell::new(Vec::new()); // dict-typed globals
}

fn tail_push(line: String) {
    TAIL.with(|t| t.borrow_mut().push(line));
}

fn add_str(counter: &mut usize, text: &str) -> String {
    let name = format!("str_{}", counter);
    *counter += 1;
    let bytes = format!("{}\x00", text);
    tail_push(format!(
        "@\"{}\" = constant [{} x i8] c\"{}\"",
        name, bytes.len(), escape_bytes(bytes.as_bytes())));
    name
}


// ---------- float support ----------

// llvmlite's double hex: right-aligned to width 16 with SPACES
fn double_bits(v: f64) -> String {
    if v == 0.0 {
        return if v.is_sign_negative() {
            format!("{:>16}", "0x8000000000000000")
        } else {
            format!("{:>16}", "0x0")
        };
    }
    let bits = v.to_bits();
    format!("{:>16}", format!("0x{:x}", bits))
}

#[derive(Clone, PartialEq)]
enum Ty { I64, F64 } // typed expression results

// ---------- block-list function builder ----------

struct FnB {
    blocks: Vec<(String, Vec<String>)>,
    cur: usize,
    anon: usize,
    reg_names: Vec<String>, // named (non-block) registrations, e.g. allocas
}

enum Slot { Global(String) } // @"name" variables (module scope)

impl FnB {
    fn new(anon_start: usize) -> FnB {
        FnB { blocks: vec![("entry".into(), Vec::new())], cur: 0,
              anon: anon_start, reg_names: Vec::new() }
    }
    fn add_block(&mut self, label: &str) -> usize {
        self.blocks.push((label.to_string(), Vec::new()));
        self.blocks.len() - 1
    }
    fn pos(&mut self, i: usize) { self.cur = i; }
    // llvmlite duplicate-name rule across the function's shared
    // namespace: same-base blocks AND named values get .1, .2, ...
    fn uniq_label(&mut self, base: &str) -> String {
        let same = |l: &str| l == base || l.starts_with(&format!("{}.", base));
        let n = self.blocks.iter().filter(|(l, _)| same(l)).count()
            + self.reg_names.iter().filter(|l| same(l)).count();
        if n == 0 { base.to_string() } else { format!("{}.{}", base, n) }
    }
    fn line(&mut self, l: String) { self.blocks[self.cur].1.push(l); }
    fn nx(&mut self) -> String { self.anon += 1; format!(".{}", self.anon) }
    fn silent(&mut self) { self.anon += 1; }
    fn panic_defs(&self) -> usize {
        self.blocks.iter().filter(|(l, _)| l.starts_with("panic_bad")).count()
    }
    // zero-division check: cbr in CURRENT block, creates the panic
    // pair, positions into panic_ok. Returns nothing (caller is in ok).
    fn zero_check(&mut self, divisor: &str, sc: &mut usize) {
        let zc = self.nx();
        self.line(format!("  %\"{}\" = icmp eq i64 {}, 0", zc, divisor));
        self.silent(); // cbr
        let suffix = self.panic_suffix();
        self.line(format!(
            "  br i1 %\"{}\", label %\"panic_bad{}\", label %\"panic_ok{}\"", zc, suffix, suffix));
        let bad = self.add_block(&format!("panic_bad{}", suffix));
        self.emit_panic_body(bad, "ZeroDivisionError: division by zero", sc);
        let ok = self.add_block(&format!("panic_ok{}", suffix));
        self.pos(ok);
    }
    // overflow check on the extracted i1: same shape, custom message
    fn overflow_check(&mut self, flag: &str, msg: &str, sc: &mut usize) {
        self.silent(); // cbr
        let suffix = self.panic_suffix();
        self.line(format!(
            "  br i1 {}, label %\"panic_bad{}\", label %\"panic_ok{}\"", flag, suffix, suffix));
        let bad = self.add_block(&format!("panic_bad{}", suffix));
        self.emit_panic_body(bad, msg, sc);
        let ok = self.add_block(&format!("panic_ok{}", suffix));
        self.pos(ok);
    }
    fn panic_suffix(&self) -> String {
        let n = self.panic_defs();
        if n == 0 { String::new() } else { format!(".{}", n) }
    }
    fn emit_panic_body(&mut self, bad: usize, msg: &str, sc: &mut usize) {
        let name = add_str(sc, msg);
        let g = self.nx();
        let len = msg.len() + 1;
        self.blocks[bad].1.push(format!(
            "  %\"{}\" = getelementptr [{} x i8], [{} x i8]* @\"{}\", i32 0, i32 0",
            g, len, len, name));
        self.silent(); // void call
        self.blocks[bad].1.push(format!("  call void @\"silu_panic\"(i8* %\"{}\")", g));
        self.silent(); // unreachable
        self.blocks[bad].1.push("  unreachable".into());
    }
    // checked add/sub: returns the value ref
    fn checked_addsub(&mut self, lhs: &str, rhs: &str, which: &str, sc: &mut usize) -> String {
        let (intrinsic, msg) = if which == "+" {
            ("llvm.sadd.with.overflow.i64", "OverflowError: integer overflow in add")
        } else {
            ("llvm.ssub.with.overflow.i64", "OverflowError: integer overflow in sub")
        };
        let c = self.nx();
        self.line(format!(
            "  %\"{}\" = call {{i64, i1}} @\"{}\"(i64 {}, i64 {})", c, intrinsic, lhs, rhs));
        let v0 = self.nx();
        self.line(format!("  %\"{}\" = extractvalue {{i64, i1}} %\"{}\", 0", v0, c));
        let v1 = self.nx();
        self.line(format!("  %\"{}\" = extractvalue {{i64, i1}} %\"{}\", 1", v1, c));
        self.overflow_check(&format!("%\"{}\"", v1), msg, sc);
        format!("%\"{}\"", v0)
    }
    fn checked_mul(&mut self, lhs: &str, rhs: &str, sc: &mut usize) -> String {
        let c = self.nx();
        self.line(format!(
            "  %\"{}\" = call {{i64, i1}} @\"llvm.smul.with.overflow.i64\"(i64 {}, i64 {})",
            c, lhs, rhs));
        let v0 = self.nx();
        self.line(format!("  %\"{}\" = extractvalue {{i64, i1}} %\"{}\", 0", v0, c));
        let v1 = self.nx();
        self.line(format!("  %\"{}\" = extractvalue {{i64, i1}} %\"{}\", 1", v1, c));
        self.overflow_check(&format!("%\"{}\"", v1),
            "OverflowError: integer overflow in mul", sc);
        format!("%\"{}\"", v0)
    }

    // float zero check: fcmp oeq against +0.0 (llvmlite pads hex)
    fn fzero_check(&mut self, divisor: &str, sc: &mut usize) {
        let zc = self.nx();
        self.line(format!("  %\"{}\" = fcmp oeq double {}, {}",
                          zc, divisor, format!("{:>16}", "0x0")));
        self.silent();
        let suffix = self.panic_suffix();
        self.line(format!(
            "  br i1 %\"{}\", label %\"panic_bad{}\", label %\"panic_ok{}\"",
            zc, suffix, suffix));
        let bad = self.add_block(&format!("panic_bad{}", suffix));
        self.emit_panic_body(bad, "ZeroDivisionError: division by zero", sc);
        let ok = self.add_block(&format!("panic_ok{}", suffix));
        self.pos(ok);
    }

    // Python %: srem + sign fixup. Divisor as bare text (const or %ref).
    fn py_mod(&mut self, a: &str, b: &str, sc: &mut usize) -> String {
        self.zero_check(b, sc);
        let r = self.nx();
        self.line(format!("  %\"{}\" = srem i64 {}, {}", r, a, b));
        self.sign_fixup(&format!("%\"{}\"", r), b, b)
    }
    // Python //: sdiv + remainder-sign adjustment (-1)
    fn py_floordiv(&mut self, a: &str, b: &str, sc: &mut usize) -> String {
        self.zero_check(b, sc);
        let q = self.nx();
        self.line(format!("  %\"{}\" = sdiv i64 {}, {}", q, a, b));
        let r = self.nx();
        self.line(format!("  %\"{}\" = srem i64 {}, {}", r, a, b));
        // select adjust (shared shape with py_mod, no internal add)
        let n1 = self.nx();
        self.line(format!("  %\"{}\" = icmp ne i64 %\"{}\", 0", n1, r));
        let n2 = self.nx();
        self.line(format!("  %\"{}\" = icmp slt i64 %\"{}\", 0", n2, r));
        let n3 = self.nx();
        self.line(format!("  %\"{}\" = icmp slt i64 {}, 0", n3, b));
        let n4 = self.nx();
        self.line(format!("  %\"{}\" = xor i1 %\"{}\", %\"{}\"", n4, n2, n3));
        let n5 = self.nx();
        self.line(format!("  %\"{}\" = and i1 %\"{}\", %\"{}\"", n5, n1, n4));
        let n6 = self.nx();
        self.line(format!("  %\"{}\" = select  i1 %\"{}\", i64 -1, i64 0", n6, n5));
        let n7 = self.nx();
        self.line(format!("  %\"{}\" = add i64 %\"{}\", %\"{}\"", n7, q, n6));
        format!("%\"{}\"", n7)
    }
    // r != 0 && sign(r) != sign(b) ? adjust : 0 ; returns r+adjust ref
    fn sign_fixup(&mut self, r: &str, b: &str, adjust: &str) -> String {
        let n1 = self.nx();
        self.line(format!("  %\"{}\" = icmp ne i64 {}, 0", n1, r));
        let n2 = self.nx();
        self.line(format!("  %\"{}\" = icmp slt i64 {}, 0", n2, r));
        let n3 = self.nx();
        self.line(format!("  %\"{}\" = icmp slt i64 {}, 0", n3, b));
        let n4 = self.nx();
        self.line(format!("  %\"{}\" = xor i1 %\"{}\", %\"{}\"", n4, n2, n3));
        let n5 = self.nx();
        self.line(format!("  %\"{}\" = and i1 %\"{}\", %\"{}\"", n5, n1, n4));
        let n6 = self.nx();
        self.line(format!("  %\"{}\" = select  i1 %\"{}\", i64 {}, i64 0", n6, n5, adjust));
        let n7 = self.nx();
        self.line(format!("  %\"{}\" = add i64 {}, %\"{}\"", n7, r, n6));
        format!("%\"{}\"", n7)
    }
    // list element READ with bounds check + Python negative indexing.
    // objref/idx are ready refs; cursor continues in get_ok. Returns the
    // loaded i64 ref. Every read creates its own IndexError string.
    fn list_get(&mut self, objref: &str, idx: &str, sc: &mut usize) -> String {
        let bc = self.nx();
        self.line(format!(
            "  %\"{}\" = bitcast i8* {} to {{i64, i64, i8*}}*", bc, objref));
        let gl = self.nx();
        self.line(format!(
            "  %\"{}\" = getelementptr {{i64, i64, i8*}}, {{i64, i64, i8*}}* %\"{}\", i32 0, i32 0",
            gl, bc));
        let len = self.nx();
        self.line(format!("  %\"{}\" = load i64, i64* %\"{}\"", len, gl));
        let gd = self.nx();
        self.line(format!(
            "  %\"{}\" = getelementptr {{i64, i64, i8*}}, {{i64, i64, i8*}}* %\"{}\", i32 0, i32 2",
            gd, bc));
        let data = self.nx();
        self.line(format!("  %\"{}\" = load i8*, i8** %\"{}\"", data, gd));
        let neg = self.nx();
        self.line(format!("  %\"{}\" = icmp slt i64 {}, 0", neg, idx));
        let sum = self.nx();
        self.line(format!("  %\"{}\" = add i64 {}, %\"{}\"", sum, idx, len));
        let sel = self.nx();
        self.line(format!(
            "  %\"{}\" = select  i1 %\"{}\", i64 %\"{}\", i64 {}",
            sel, neg, sum, idx));
        let lt = self.nx();
        self.line(format!("  %\"{}\" = icmp slt i64 %\"{}\", %\"{}\"", lt, sel, len));
        let ok_lbl = self.uniq_label("get_ok");
        let err_lbl = self.uniq_label("get_err");
        self.silent();
        self.line(format!(
            "  br i1 %\"{}\", label %\"{}\", label %\"{}\"", lt, ok_lbl, err_lbl));
        let ob = self.add_block(&ok_lbl);
        self.pos(ob);
        let eb = self.add_block(&err_lbl);
        self.emit_panic_body(eb, "IndexError: list index out of range", sc);
        let dbc = self.nx();
        self.line(format!("  %\"{}\" = bitcast i8* %\"{}\" to i64*", dbc, data));
        let gep = self.nx();
        self.line(format!(
            "  %\"{}\" = getelementptr i64, i64* %\"{}\", i64 %\"{}\"", gep, dbc, sel));
        let ld = self.nx();
        self.line(format!("  %\"{}\" = load i64, i64* %\"{}\"", ld, gep));
        format!("%\"{}\"", ld)
    }

    // list element WRITE: bounds-check chain + store. objref/keyref/valref
    // are ready (caller ordered: obj, key, value); cursor continues in
    // set_ok. Fresh IndexError string per write (47B variant).
    fn list_set(&mut self, objref: &str, key: &str, val: &str, sc: &mut usize) {
        let bc = self.nx();
        self.line(format!(
            "  %\"{}\" = bitcast i8* {} to {{i64, i64, i8*}}*", bc, objref));
        let gl = self.nx();
        self.line(format!(
            "  %\"{}\" = getelementptr {{i64, i64, i8*}}, {{i64, i64, i8*}}* %\"{}\", i32 0, i32 0",
            gl, bc));
        let len = self.nx();
        self.line(format!("  %\"{}\" = load i64, i64* %\"{}\"", len, gl));
        let gd = self.nx();
        self.line(format!(
            "  %\"{}\" = getelementptr {{i64, i64, i8*}}, {{i64, i64, i8*}}* %\"{}\", i32 0, i32 2",
            gd, bc));
        let data = self.nx();
        self.line(format!("  %\"{}\" = load i8*, i8** %\"{}\"", data, gd));
        let neg = self.nx();
        self.line(format!("  %\"{}\" = icmp slt i64 {}, 0", neg, key));
        let sum = self.nx();
        self.line(format!("  %\"{}\" = add i64 {}, %\"{}\"", sum, key, len));
        let sel = self.nx();
        self.line(format!(
            "  %\"{}\" = select  i1 %\"{}\", i64 %\"{}\", i64 {}",
            sel, neg, sum, key));
        let lt = self.nx();
        self.line(format!("  %\"{}\" = icmp slt i64 %\"{}\", %\"{}\"", lt, sel, len));
        let ok_lbl = self.uniq_label("set_ok");
        let err_lbl = self.uniq_label("set_err");
        self.silent();
        self.line(format!(
            "  br i1 %\"{}\", label %\"{}\", label %\"{}\"", lt, ok_lbl, err_lbl));
        let ob = self.add_block(&ok_lbl);
        self.pos(ob);
        let eb = self.add_block(&err_lbl);
        self.emit_panic_body(eb,
            "IndexError: list assignment index out of range", sc);
        let dbc = self.nx();
        self.line(format!("  %\"{}\" = bitcast i8* %\"{}\" to i64*", dbc, data));
        let gep = self.nx();
        self.line(format!(
            "  %\"{}\" = getelementptr i64, i64* %\"{}\", i64 %\"{}\"", gep, dbc, sel));
        self.silent();
        self.line(format!("  store i64 {}, i64* %\"{}\"", val, gep));
    }

    // i64 value expression in the CURRENT block against a variable slot
    // kind (global @"x" or local %"x"); full arith via eval_expr
    fn expr_i64(&mut self, e: &Val, slot_ref: &dyn Fn(&str) -> String) -> String {
        let fs = F_SLOTS.with(|f| f.borrow().clone());
        let v = eval_expr(self, e, slot_ref, slot_ref,
                          unsafe { &mut *SC_PTR }, &fs);
        match v {
            Typed::I64(r) => r,
            _ => bail("expr_i64 type"),
        }
    }
    fn line_store(&mut self, n: i64) {
        self.silent();
        self.line(format!("  store i64 {}, i64* @\"__silu_line\"", n));
    }
    fn render(&self, header: &str) -> String {
        let mut out = String::new();
        out.push_str(header);
        out.push_str("{\n");
        for (label, lines) in &self.blocks {
            out.push_str(label);
            out.push_str(":\n");
            for l in lines {
                out.push_str(l);
                out.push('\n');
            }
        }
        out.push_str("}\n\n");
        out
    }
}

// shared module string counter via raw pointer (single-threaded main)
static mut SC_PTR: *mut usize = std::ptr::null_mut();

fn global_slot(n: &str) -> String { format!("@\"{}\"", n) }
fn local_slot(n: &str) -> String { format!("%\"{}\"", n) }

// ---------- statement converters ----------

// aug_assign to a name slot with the given slot_ref (global or local)
fn conv_aug_assign(b: &mut FnB, st: &Val, sc: &mut usize,
                   slot_ref: &dyn Fn(&str) -> String) {
    let slot = st.get(1).get(1).str_of();
    let op = st.get(2).str_of();
    let rhs_e = st.get(3);
    let rhs = b.expr_i64_raw(&rhs_e, slot_ref, sc);
    let which = match op.as_str() {
        "+=" => "+", "-=" => "-", _ => bail("aug op"),
    };
    let target = slot_ref(&slot);
    let l = b.nx_raw();
    b.line_raw(format!("  %\"{}\" = load i64, i64* {}", l, target));
    let res = b.checked_raw(&format!("%\"{}\"", l), &rhs, which, sc);
    b.silent_raw();
    b.line_raw(format!("  store i64 {}, i64* {}", res, target));
}

// extra raw-pass-through helpers on FnB used by conv_aug_assign
// (borrow gymnastics kept out of the statement layer)
impl FnB {
    fn expr_i64_raw(&mut self, e: &Val, slot_ref: &dyn Fn(&str) -> String,
                    sc: &mut usize) -> String {
        unsafe { SC_PTR = sc; }
        self.expr_i64(e, slot_ref)
    }
    fn nx_raw(&mut self) -> String { self.nx() }
    fn silent_raw(&mut self) { self.silent(); }
    fn line_raw(&mut self, l: String) { self.line(l); }
    fn checked_raw(&mut self, lhs: &str, rhs: &str, which: &str,
                   sc: &mut usize) -> String {
        unsafe { SC_PTR = sc; }
        self.checked_addsub(lhs, rhs, which, unsafe { &mut *SC_PTR })
    }
}

// shared float-global registry (thread-local so the recursive block
// converter can update it from any nesting depth)
thread_local! {
    static F_SLOTS: RefCell<Vec<String>> = RefCell::new(Vec::new());
    static FUNC_DEFS: RefCell<Vec<Val>> = RefCell::new(Vec::new());
}

fn is_declared(name: &str) -> bool {
    TAIL.with(|t| t.borrow().iter()
        .any(|g| g.contains(&format!("@\"{}\"", name))))
}

// int/float comparison condition -> i1 ref; ops shared by while/if
fn emit_cond(b: &mut FnB, cond: &Val, sc: &mut usize) -> String {
    let pred = match cond.head() {
        "<" => "slt", "<=" => "sle", ">" => "sgt", ">=" => "sge",
        "==" => "eq", "!=" => "ne",
        _ => bail("cond op"),
    };
    let fs = F_SLOTS.with(|f| f.borrow().clone());
    let lhs = eval_mod(b, &cond.get(1), &fs, sc);
    let rhs = eval_mod(b, &cond.get(2), &fs, sc);
    let ic = b.nx();
    if matches!(lhs, Typed::F64(_)) || matches!(rhs, Typed::F64(_)) {
        let l = to_f64(b, lhs);
        let r = to_f64(b, rhs);
        let fp = match pred { "slt" => "olt", "sle" => "ole",
                             "sgt" => "ogt", "sge" => "oge",
                             "eq" => "oeq", _ => "one" };
        b.line(format!("  %\"{}\" = fcmp {} double {}, {}", ic, fp, l, r));
    } else {
        let (Typed::I64(l), Typed::I64(r)) = (lhs, rhs) else {
            bail("cond types") };
        b.line(format!("  %\"{}\" = icmp {} i64 {}, {}", ic, pred, l, r));
    }
    format!("%\"{}\"", ic)
}

// [0] * n fill loop: rawlist_new then inline fill_cond/body/end; the
// new register is stored to the global in fill_end (fannkuch evidence)
fn emit_fill(b: &mut FnB, name: &str, fill: &Val, count_e: &Val, sc: &mut usize) {
    let fs = F_SLOTS.with(|f| f.borrow().clone());
    let cnt = {
        let v = eval_mod(b, count_e, &fs, sc);
        let Typed::I64(r) = v else { bail("fill count type") };
        r
    };
    let fillval = match fill.items().get(1) {
        Some(Val::List(vs)) if vs.len() == 1 => match &vs[0] {
            Val::List(el) if el.len() == 2 && el[0] == Val::Str("const".into())
                && matches!(el[1], Val::Int(_)) => el[1].int_of(),
            _ => bail("fill value"),
        },
        _ => bail("fill value"),
    };
    let c = b.nx();
    b.line(format!("  %\"{}\" = call i8* @\"rawlist_new\"(i64 8)", c));
    let fln = b.uniq_label("fill_list");
    b.reg_names.push(fln.clone());
    b.line(format!("  %\"{}\" = alloca i8*", fln));
    b.silent();
    b.line(format!("  store i8* %\"{}\", i8** %\"{}\"", c, fln));
    let fin = b.uniq_label("fill_i");
    b.reg_names.push(fin.clone());
    b.line(format!("  %\"{}\" = alloca i64", fin));
    b.silent();
    b.line(format!("  store i64 0, i64* %\"{}\"", fin));
    let fc_lbl = b.uniq_label("fill_cond");
    b.silent();
    b.line(format!("  br label %\"{}\"", fc_lbl));
    let fc_b = b.add_block(&fc_lbl);
    let fb_lbl = b.uniq_label("fill_body");
    let fb_b = b.add_block(&fb_lbl);
    let fe_lbl = b.uniq_label("fill_end");
    let fe_b = b.add_block(&fe_lbl);
    b.pos(fc_b);
    let idx = b.nx();
    b.line(format!("  %\"{}\" = load i64, i64* %\"{}\"", idx, fin));
    let ic = b.nx();
    b.line(format!("  %\"{}\" = icmp slt i64 %\"{}\", {}", ic, idx, cnt));
    b.silent();
    b.line(format!(
        "  br i1 %\"{}\", label %\"{}\", label %\"{}\"", ic, fb_lbl, fe_lbl));
    b.pos(fb_b);
    let lp = b.nx();
    b.line(format!("  %\"{}\" = load i8*, i8** %\"{}\"", lp, fln));
    let pu = b.nx();
    b.line(format!(
        "  %\"{}\" = call i64 @\"rawlist_push\"(i8* %\"{}\", i64 {})", pu, lp, fillval));
    let inc = b.nx();
    b.line(format!("  %\"{}\" = add i64 %\"{}\", 1", inc, idx));
    b.silent();
    b.line(format!("  store i64 %\"{}\", i64* %\"{}\"", inc, fin));
    b.silent();
    b.line(format!("  br label %\"{}\"", fc_lbl));
    b.pos(fe_b);
    b.silent();
    b.line(format!("  store i8* %\"{}\", i8** @\"{}\"", c, name));
}

// ann_assign: typed module binding (dict/list/str/float/int), usable at
// any nesting depth in main
fn conv_ann_assign(b: &mut FnB, st: &Val, sc: &mut usize) {
    let name = st.get(1).str_of();
    let init = st.get(2);
    if st.get(3).head() == "subscript"
        && st.get(3).get(1).get(1).str_of() == "dict" {
        let tp = st.get(3).get(2);
        let tv = tp.items().get(1).cloned().unwrap_or(Val::Null);
        let ok_types = tp.head() == "tuple"
            && matches!(&tv, Val::List(vs) if vs.len() == 2
                && vs.iter().all(|v| v.get(1).str_of() == "int"));
        if !ok_types { bail("dict elem types"); }
        if init.head() != "dict"
            || !matches!(init.items().get(1), Some(Val::List(v)) if v.is_empty()) {
            bail("dict init");
        }
        *sc += 1; // module binding consumes a slot
        DCT_SLOTS.with(|t| t.borrow_mut().push(name.clone()));
        let c = b.nx();
        b.line(format!("  %\"{}\" = call i8* @\"rawdict_new\"()", c));
        b.silent();
        b.line(format!("  store i8* %\"{}\", i8** @\"{}\"", c, name));
        tail_push(format!("@\"{}\" = global i8* null", name));
    } else if st.get(3).head() == "subscript"
        && st.get(3).get(1).get(1).str_of() == "list" {
        let elem = st.get(3).get(2).get(1).str_of();
        if elem != "int" { bail("list elem type"); }
        *sc += 1; // module binding consumes a slot
        LST_SLOTS.with(|t| t.borrow_mut().push(name.clone()));
        if init.head() == "list" {
            // [] literal or [v] * n fill loop
            let elems = init.items().get(1).cloned().unwrap_or(Val::Null);
            if matches!(&elems, Val::List(v) if v.is_empty()) {
                let c = b.nx();
                b.line(format!("  %\"{}\" = call i8* @\"rawlist_new\"(i64 8)", c));
                b.silent();
                b.line(format!("  store i8* %\"{}\", i8** @\"{}\"", c, name));
            } else if init.head() == "list" {
                // multiplication form handled by caller context below
                bail("list init");
            }
        } else if init.head() == "*" {
            emit_fill(b, &name, &init.get(1), &init.get(2), sc);
        } else { bail("list init"); }
        tail_push(format!("@\"{}\" = global i8* null", name));
    } else {
        let anno = st.get(3).get(1).str_of();
        if anno == "str" {
            STR_SLOTS.with(|sl| sl.borrow_mut().push(name.clone()));
            let text = match &init.items()[1] { Val::Str(v) => v.clone(),
                                                _ => String::new() };
            let gname = add_str(sc, &text);
            *sc += 1; // the binding itself consumes a slot after the init const
            let g = b.nx();
            let blen = text.chars().count();
            b.line(format!(
                "  %\"{}\" = getelementptr [{} x i8], [{} x i8]* @\"{}\", i32 0, i32 0",
                g, blen + 1, blen + 1, gname));
            let c = b.nx();
            b.line(format!(
                "  %\"{}\" = call {{i32, i8*}}* @\"create_str\"(i8* %\"{}\", i32 {})",
                c, g, blen));
            let pr = b.nx();
            b.line(format!(
                "  %\"{}\" = call i8* @\"pystr_to_rawstr\"({{i32, i8*}}* %\"{}\")",
                pr, c));
            let old = b.nx();
            b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", old, name));
            b.silent();
            b.line(format!("  call void @\"rawstr_free\"(i8* %\"{}\")", old));
            b.silent();
            b.line(format!("  store i8* %\"{}\", i8** @\"{}\"", pr, name));
            tail_push(format!("@\"{}\" = global i8* null", name));
        } else if anno == "float" {
            *sc += 1; // module binding consumes a slot (no init string)
            F_SLOTS.with(|f| f.borrow_mut().push(name.clone()));
            let f = match &init.items()[1] { Val::Float(v) => *v, _ => 0.0 };
            tail_push(format!("@\"{}\" = global double {}",
                              name, double_bits(f)));
            b.silent();
            b.line(format!("  store double {}, double* @\"{}\"",
                           double_bits(f), name));
        } else {
            // int binding: slot + global first, then init
            *sc += 1; // module binding consumes a slot (no init string)
            tail_push(format!("@\"{}\" = global i64 0", name));
            if init.head() == "const" && matches!(init.get(1), Val::Int(_)) {
                b.silent();
                b.line(format!("  store i64 {}, i64* @\"{}\"",
                               init.get(1).int_of(), name));
            } else if init.head() == "name" {
                let src = init.get(1).str_of();
                let l = b.nx();
                b.line(format!("  %\"{}\" = load i64, i64* @\"{}\"", l, src));
                b.silent();
                b.line(format!("  store i64 %\"{}\", i64* @\"{}\"", l, name));
            } else {
                let fs = F_SLOTS.with(|f| f.borrow().clone());
                let v = eval_mod(b, &init, &fs, sc);
                let Typed::I64(r) = v else { bail("ann_assign type") };
                b.silent();
                b.line(format!("  store i64 {}, i64* @\"{}\"", r, name));
            }
        }
    }
}

// plain assign: float/str paths keep their shapes; int target stores the
// evaluated rhs; an UNDECLARED name auto-registers a global + slot AFTER
// the rhs eval (fannkuch k/tmp/j evidence)
fn conv_assign(b: &mut FnB, st: &Val, sc: &mut usize) {
    let name = st.get(1).str_of();
    let rhs = st.get(2);
    let is_f = F_SLOTS.with(|f| f.borrow().iter().any(|x| x == &name));
    let is_s = STR_SLOTS.with(|s| s.borrow().iter().any(|x| x == &name));
    if is_f {
        let fs = F_SLOTS.with(|f| f.borrow().clone());
        let v = eval_mod(b, &rhs, &fs, sc);
        let r = to_f64(b, v);
        b.silent();
        b.line(format!("  store double {}, double* @\"{}\"", r, name));
    } else if is_s {
        if rhs.head() == "+" {
            // s = s + "lit" -> rawstr_append(s, lit, len)
            let lit = match &rhs.get(2).items()[1] {
                Val::Str(v) => v.clone(), _ => bail("str rhs") };
            let gname = add_str(sc, &lit);
            let g = b.nx();
            let blen = lit.chars().count();
            b.line(format!(
                "  %\"{}\" = getelementptr [{} x i8], [{} x i8]* @\"{}\", i32 0, i32 0",
                g, blen + 1, blen + 1, gname));
            let l = b.nx();
            b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, name));
            b.silent(); // rawstr_append
            b.line(format!(
                "  call void @\"rawstr_append\"(i8* %\"{}\", i8* %\"{}\", i64 {})",
                l, g, blen));
        } else { bail("str assign rhs"); }
    } else {
        if LST_SLOTS.with(|t| t.borrow().iter().any(|x| x == &name))
            || DCT_SLOTS.with(|t| t.borrow().iter().any(|x| x == &name)) {
            bail("assign to container");
        }
        let fs = F_SLOTS.with(|f| f.borrow().clone());
        let v = eval_mod(b, &rhs, &fs, sc);
        let Typed::I64(r) = v else { bail("assign type") };
        if !is_declared(&name) {
            *sc += 1; // auto-registered binding
            tail_push(format!("@\"{}\" = global i64 0", name));
        }
        b.silent();
        b.line(format!("  store i64 {}, i64* @\"{}\"", r, name));
    }
}

// subscript store: dict keeps (obj, value, key) + rawdict_set; list uses
// (obj, key, value) + bounds-checked element store
fn conv_subscript_assign(b: &mut FnB, st: &Val, sc: &mut usize) {
    if st.get(1).head() != "name" { bail("subscript_assign base"); }
    let obj = st.get(1).get(1).str_of();
    if DCT_SLOTS.with(|t| t.borrow().iter().any(|f| f == &obj)) {
        let l = b.nx();
        b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, obj));
        let v = b.expr_i64_raw(&st.get(3), &global_slot, sc);
        let k = b.expr_i64_raw(&st.get(2), &global_slot, sc);
        b.silent();
        b.line(format!(
            "  call void @\"rawdict_set\"(i8* %\"{}\", i64 {}, i64 {})",
            l, k, v));
    } else if LST_SLOTS.with(|t| t.borrow().iter().any(|f| f == &obj)) {
        let l = b.nx(); // obj load, then key eval, then value eval
        b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, obj));
        let k = b.expr_i64_raw(&st.get(2), &global_slot, sc);
        let v = b.expr_i64_raw(&st.get(3), &global_slot, sc);
        b.list_set(&format!("%\"{}\"", l), &k, &v, sc);
    } else { bail("subscript_assign target"); }
}

// recursive main-body statement converter; `loops` stacks enclosing
// loop-end labels for break. Returns true when the current block was
// terminated (break) so callers skip their trailing br.
fn conv_block(b: &mut FnB, stmts: &[Val], loops: &mut Vec<String>,
              sc: &mut usize) -> bool {
    let mut i = 0usize;
    while i < stmts.len() {
        let st = stmts[i].clone();
        if !matches!(st, Val::List(_)) { i += 1; continue; }
        match st.head() {
            "line" => { b.line_store(st.get(1).int_of()); }
            "ann_assign" => { conv_ann_assign(b, &st, sc); }
            "assign" => { conv_assign(b, &st, sc); }
            "aug_assign" => {
                conv_aug_assign(b, &st, sc, &global_slot);
            }
            "subscript_assign" => { conv_subscript_assign(b, &st, sc); }
            "call" if st.get(1).head() == "name"
                     && st.get(1).get(1).str_of() == "print" => {
                conv_print(b, &st, sc);
            }
            "call" if st.get(1).head() == "attribute"
                     && st.get(1).get(2).str_of() == "append" => {
                let obj = st.get(1).get(1).get(1).str_of();
                if !LST_SLOTS.with(|t| t.borrow().iter()
                        .any(|f| f == &obj)) { bail("append target"); }
                let args = st.get(2).items();
                if args.len() != 1 { bail("append arity"); }
                let l = b.nx(); // object load first, then arg eval
                b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, obj));
                let v = b.expr_i64_raw(&args[0], &global_slot, sc);
                let c = b.nx();
                b.line(format!(
                    "  %\"{}\" = call i64 @\"rawlist_push\"(i8* %\"{}\", i64 {})",
                    c, l, v));
            }
            "while" => {
                let body = st.get(2).items();
                let cond_lbl = b.uniq_label("while_cond");
                let cond_b = b.add_block(&cond_lbl);
                let body_lbl = b.uniq_label("while_body");
                let body_b = b.add_block(&body_lbl);
                let end_lbl = b.uniq_label("while_end");
                let end_b = b.add_block(&end_lbl);
                b.silent();
                b.line(format!("  br label %\"{}\"", cond_lbl));
                b.pos(cond_b);
                let ic = emit_cond(b, &st.get(1), sc);
                b.silent();
                b.line(format!(
                    "  br i1 {}, label %\"{}\", label %\"{}\"",
                    ic, body_lbl, end_lbl));
                b.pos(body_b);
                loops.push(end_lbl.clone());
                conv_block(b, &body, loops, sc);
                loops.pop();
                b.silent();
                b.line(format!("  br label %\"{}\"", cond_lbl));
                b.pos(end_b);
            }
            "for" => {
                if st.get(1).head() != "name" { bail("for target"); }
                if st.get(2).head() != "name" { bail("for iter"); }
                if !st.get(4).items().is_empty() { bail("for orelse"); }
                let target = st.get(1).get(1).str_of();
                let iname = st.get(2).get(1).str_of();
                if !LST_SLOTS.with(|t| t.borrow().iter().any(|f| f == &iname)) {
                    bail("for iter type");
                }
                if is_declared(&target) { bail("dup for target"); }
                *sc += 1; // target binding consumes a module slot
                tail_push(format!("@\"{}\" = global i64 0", target));
                let body = st.get(3).items();

                let l = b.nx();
                b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, iname));
                let idxn = b.uniq_label("riter_idx");
                b.reg_names.push(idxn.clone());
                b.line(format!("  %\"{}\" = alloca i64", idxn));
                b.silent();
                b.line(format!("  store i64 0, i64* %\"{}\"", idxn));
                let lenc = b.nx();
                b.line(format!(
                    "  %\"{}\" = call i64 @\"rawlist_len\"(i8* %\"{}\")", lenc, l));
                b.silent();
                let rc_lbl = b.uniq_label("riter_cond");
                b.line(format!("  br label %\"{}\"", rc_lbl));
                let cond_b = b.add_block(&rc_lbl);
                let rb_lbl = b.uniq_label("riter_body");
                let body_b = b.add_block(&rb_lbl);
                let ri_lbl = b.uniq_label("riter_incr");
                let incr_b = b.add_block(&ri_lbl);
                let re_lbl = b.uniq_label("riter_end");
                let end_b = b.add_block(&re_lbl);
                b.pos(cond_b);
                let idx = b.nx();
                b.line(format!("  %\"{}\" = load i64, i64* %\"{}\"", idx, idxn));
                let ic = b.nx();
                b.line(format!(
                    "  %\"{}\" = icmp slt i64 %\"{}\", %\"{}\"", ic, idx, lenc));
                b.silent();
                b.line(format!(
                    "  br i1 %\"{}\", label %\"{}\", label %\"{}\"",
                    ic, rb_lbl, re_lbl));
                b.pos(body_b);
                let bc = b.nx();
                b.line(format!(
                    "  %\"{}\" = bitcast i8* %\"{}\" to {{i64, i64, i8*}}*", bc, l));
                let gp = b.nx();
                b.line(format!(
                    "  %\"{}\" = getelementptr {{i64, i64, i8*}}, {{i64, i64, i8*}}* %\"{}\", i32 0, i32 2",
                    gp, bc));
                let dp = b.nx();
                b.line(format!("  %\"{}\" = load i8*, i8** %\"{}\"", dp, gp));
                let bc2 = b.nx();
                b.line(format!("  %\"{}\" = bitcast i8* %\"{}\" to i64*", bc2, dp));
                let ep = b.nx();
                b.line(format!(
                    "  %\"{}\" = getelementptr i64, i64* %\"{}\", i64 %\"{}\"",
                    ep, bc2, idx));
                let el = b.nx();
                b.line(format!("  %\"{}\" = load i64, i64* %\"{}\"", el, ep));
                b.silent();
                b.line(format!("  store i64 %\"{}\", i64* @\"{}\"", el, target));
                loops.push(re_lbl.clone());
                conv_block(b, &body, loops, sc);
                loops.pop();
                b.silent();
                b.line(format!("  br label %\"{}\"", ri_lbl));
                b.pos(incr_b);
                let il = b.nx();
                b.line(format!("  %\"{}\" = load i64, i64* %\"{}\"", il, idxn));
                let ia = b.nx();
                b.line(format!("  %\"{}\" = add i64 %\"{}\", 1", ia, il));
                b.silent();
                b.line(format!("  store i64 %\"{}\", i64* %\"{}\"", ia, idxn));
                b.silent();
                b.line(format!("  br label %\"{}\"", rc_lbl));
                b.pos(end_b);
            }
            "if" => {
                let then_body = st.get(2).items();
                let orelse = st.get(3).items();
                let ic = emit_cond(b, &st.get(1), sc);
                let t_lbl = b.uniq_label("if_then");
                let t_b = b.add_block(&t_lbl);
                let e_lbl = b.uniq_label("if_else");
                let e_b = b.add_block(&e_lbl);
                let m_lbl = b.uniq_label("if_merge");
                let m_b = b.add_block(&m_lbl);
                b.silent();
                b.line(format!(
                    "  br i1 {}, label %\"{}\", label %\"{}\"", ic, t_lbl, e_lbl));
                b.pos(t_b);
                let t_term = conv_block(b, &then_body, loops, sc);
                if !t_term {
                    b.silent();
                    b.line(format!("  br label %\"{}\"", m_lbl));
                }
                b.pos(e_b);
                let e_term = conv_block(b, &orelse, loops, sc);
                if !e_term {
                    b.silent();
                    b.line(format!("  br label %\"{}\"", m_lbl));
                }
                b.pos(m_b);
            }
            "break" => {
                let end = loops.last().cloned()
                    .unwrap_or_else(|| bail("break outside loop"));
                b.silent();
                b.line(format!("  br label %\"{}\"", end));
                return true;
            }
            "func_def" => {
                *sc += 1;
                FUNC_DEFS.with(|f| f.borrow_mut().push(st.clone()));
            }
            _ => bail(st.head()),
        }
        i += 1;
    }
    false
}

// module-level walk (main body). Returns fn_defs; globals land in TAIL.
fn walk_module(stmts: &[Val], sc: &mut usize) -> Vec<Val> {
    let mut b = FnB::new(1); // .1 = main ret slot
    let mut loops: Vec<String> = Vec::new();
    conv_block(&mut b, stmts, &mut loops, sc);
    b.silent(); // ret
    b.line("  ret i32 0".into());
    unsafe {
        MAIN_OUT = Some(b.render("define i32 @\"main\"()\n"));
    }
    FUNC_DEFS.with(|f| f.borrow().clone())
}

static mut MAIN_OUT: Option<String> = None;

// fib-shape function: annotated int params/ret, if + return + checked ops
fn convert_func(fd: &Val, sc: &mut usize) -> String {
    let params = fd.get(2).items();
    let annos = fd.get(4).items();
    let ret_anno = fd.get(5);
    let body = fd.get(3).items();
    let name = fd.get(1).str_of();

    for (p, a) in params.iter().zip(annos.iter()) {
        if !(a.head() == "name" && a.get(1).str_of() == "int")
            || p.str_of().is_empty() { bail("non-int param"); }
    }
    if !(ret_anno.head() == "name" && ret_anno.get(1).str_of() == "int") {
        bail("non-int return");
    }

    let n = params.len();
    let mut b = FnB::new(n + 1); // .1..N args, .N+1 ret slot
    let header = format!(
        "define internal i64 @\"{}\"({}) alwaysinline\n",
        name,
        (1..=n).map(|i| format!("i64 %\".{}\"", i))
            .collect::<Vec<_>>().join(", "));

    // allocas reverse, stores forward (silent)
    let mut alloca_lines = String::new();
    for p in params.iter().rev() {
        alloca_lines.push_str(&format!("  %\"{}\" = alloca i64\n", p.str_of()));
    }
    for (i, p) in params.iter().enumerate() {
        b.silent();
        alloca_lines.push_str(&format!(
            "  store i64 %\".{}\", i64* %\"{}\"\n", i + 1, p.str_of()));
    }

    let mut j = 0usize;
    while j < body.len() {
        let st = body[j].clone();
        if st.head() == "line" { b.line_store(st.get(1).int_of()); j += 1; continue; }
        match st.head() {
            "if" => {
                let cond = st.get(1);
                let then_body = st.get(2).items();
                let orelse = st.get(3).items();
                let pred = match cond.head() {
                    "<" => "slt", "<=" => "sle", ">" => "sgt", ">=" => "sge",
                    _ => bail("if cond"),
                };
                let lhs = b.expr_i64_raw(&cond.get(1), &local_slot, sc);
                let rhs = b.expr_i64_raw(&cond.get(2), &local_slot, sc);
                let ic = b.nx();
                b.line(format!("  %\"{}\" = icmp {} i64 {}, {}", ic, pred, lhs, rhs));
                b.silent();
                b.line(format!(
                    "  br i1 %\"{}\", label %\"if_then\", label %\"if_else\"", ic));
                let then_b = b.add_block("if_then");
                let else_b = b.add_block("if_else");
                let merge_b = b.add_block("if_merge");
                b.pos(then_b);
                let mut k = 0usize;
                while k < then_body.len() {
                    let s = then_body[k].clone();
                    if s.head() == "line" { b.line_store(s.get(1).int_of()); k += 1; continue; }
                    if s.head() == "return" {
                        let v = eval_expr(&mut b, &s.get(1), &local_slot,
                                          &local_slot, sc, &[]);
                        let Typed::I64(r) = v else { bail("then ret type") };
                        b.silent();
                        b.line(format!("  ret i64 {}", r));
                        k += 1;
                        continue;
                    }
                    bail("then stmt");
                }
                if !orelse.is_empty() { bail("non-empty else"); }
                b.pos(else_b);
                b.silent();
                b.line("  br label %\"if_merge\"".into());
                b.pos(merge_b);
            }
            "return" => {
                let v = eval_expr(&mut b, &st.get(1), &local_slot,
                                  &local_slot, sc, &[]);
                let Typed::I64(r) = v else { bail("ret type") };
                b.silent();
                b.line(format!("  ret i64 {}", r));
            }
            _ => bail(st.head()),
        }
        j += 1;
    }

    // splice allocas after entry label (render puts label first)
    let mut out = b.render(&header);
    // allocas sit INSIDE entry, right after its label line
    if let Some(epos) = out.find("entry:\n") {
        out.insert_str(epos + "entry:\n".len(), &alloca_lines);
    } else {
        out.push_str(&alloca_lines);
    }
    out
}

fn expr_sub(b: &mut FnB, e: &Val, sc: &mut usize) -> String {
    let lhs_e = e.get(1);
    let rhs_e = e.get(2);
    let lhs = match lhs_e.head() {
        "name" => {
            let l = b.nx();
            b.line(format!("  %\"{}\" = load i64, i64* %\"{}\"",
                           l, lhs_e.get(1).str_of()));
            format!("%\"{}\"", l)
        }
        _ => bail("sub lhs"),
    };
    let rhs = match rhs_e.head() {
        "const" if matches!(rhs_e.get(1), Val::Int(_)) => rhs_e.get(1).int_of().to_string(),
        _ => bail("sub rhs"),
    };
    b.checked_raw(&lhs, &rhs, "-", sc)
}

fn conv_call(b: &mut FnB, call: &Val, sc: &mut usize) -> String {
    let fname = call.get(1).get(1).str_of();
    let args = call.get(2).items();
    if args.len() != 1 { bail("call arity"); }
    let a = &args[0];
    let arg_s = match a.head() {
        "const" if matches!(a.get(1), Val::Int(_)) => format!("i64 {}", a.get(1).int_of()),
        "-" => {
            let inner = expr_sub(b, a, sc);
            format!("i64 {}", inner)
        }
        _ => bail("call arg"),
    };
    let c = b.nx();
    b.line(format!("  %\"{}\" = call i64 @\"{}\"({})", c, fname, arg_s));
    format!("%\"{}\"", c)
}


#[derive(Clone)]
enum Typed { I64(String), F64(String), Str(String) }

fn eval_expr(b: &mut FnB, e: &Val, slot_i: &dyn Fn(&str) -> String,
             slot_f: &dyn Fn(&str) -> String, sc: &mut usize,
             fslots: &[String]) -> Typed {
    match e.head() {
        "const" => match &e.items()[1] {
            Val::Int(v) => Typed::I64(v.to_string()),
            Val::Float(v) => Typed::F64(double_bits(*v)),
            _ => bail("const type"),
        },
        "name" => {
            let n = e.get(1).str_of();
            let l = b.nx();
            if fslots.iter().any(|f| f == &n) {
                b.line(format!("  %\"{}\" = load double, double* {}", l, slot_f(&n)));
                return Typed::F64(format!("%\"{}\"", l));
            }
            b.line(format!("  %\"{}\" = load i64, i64* {}", l, slot_i(&n)));
            Typed::I64(format!("%\"{}\"", l))
        }
        "subscript" => {
            if e.get(1).head() != "name" { bail("subscript base"); }
            let n = e.get(1).get(1).str_of();
            let objref = if DCT_SLOTS.with(|t| t.borrow().iter().any(|f| f == &n)) {
                // dict read: load obj, key, valued rawdict_get
                let l = b.nx();
                b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, n));
                let k = eval_expr(b, &e.get(2), slot_i, slot_f, sc, fslots);
                let Typed::I64(kr) = k else { bail("dict key type") };
                let c = b.nx();
                b.line(format!(
                    "  %\"{}\" = call i64 @\"rawdict_get\"(i8* %\"{}\", i64 {})", c, l, kr));
                return Typed::I64(format!("%\"{}\"", c));
            } else if LST_SLOTS.with(|t| t.borrow().iter().any(|f| f == &n)) {
                // list read: load obj, key, bounds-checked get_ok
                let l = b.nx();
                b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, n));
                format!("%\"{}\"", l)
            } else { bail("subscript read type"); };
            let kr = eval_expr(b, &e.get(2), slot_i, slot_f, sc, fslots);
            let Typed::I64(k) = kr else { bail("list key type") };
            Typed::I64(b.list_get(&objref, &k, sc))
        }
        "call" => {
            // user function call: eval args left to right, valued call
            let fname = e.get(1).get(1).str_of();
            if e.get(1).head() != "name" { bail("call target"); }
            let args = e.get(2).items();
            let mut parts = Vec::new();
            for a in args.iter() {
                let av = eval_expr(b, a, slot_i, slot_f, sc, fslots);
                match av {
                    Typed::I64(r) => parts.push(format!("i64 {}", r)),
                    _ => bail("call arg type"),
                }
            }
            let c = b.nx();
            b.line(format!("  %\"{}\" = call i64 @\"{}\"({})",
                c, fname, parts.join(", ")));
            Typed::I64(format!("%\"{}\"", c))
        }
        "+" | "-" | "*" | "/" | "//" | "%" => {
            let lt = eval_expr(b, &e.get(1), slot_i, slot_f, sc, fslots);
            let rt = eval_expr(b, &e.get(2), slot_i, slot_f, sc, fslots);
            let op = e.head();
            // float plane: promote int side
            if matches!(lt, Typed::F64(_)) || matches!(rt, Typed::F64(_)) {
                let l = to_f64(b, lt);
                let r = to_f64(b, rt);
                if op == "/" {
                    let rtxt = r.clone();
                    b.fzero_check(&rtxt, sc);
                    let d = b.nx();
                    b.line(format!("  %\"{}\" = fdiv double {}, {}", d, l, r));
                    return Typed::F64(format!("%\"{}\"", d));
                }
                let instr = match op { "+" => "fadd", "-" => "fsub",
                                       "*" => "fmul", _ => bail("float op") };
                let v = b.nx();
                b.line(format!("  %\"{}\" = {} double {}, {}", v, instr, l, r));
                return Typed::F64(format!("%\"{}\"", v));
            }
            let (l, r) = match (lt, rt) {
                (Typed::I64(a), Typed::I64(b)) => (a, b),
                _ => bail("mixed"),
            };
            match op {
                "+" => { let v = b.checked_addsub(&l, &r, "+", sc); Typed::I64(v) }
                "-" => { let v = b.checked_addsub(&l, &r, "-", sc); Typed::I64(v) }
                "*" => { let v = b.checked_mul(&l, &r, sc); Typed::I64(v) }
                "%" => { let v = b.py_mod(&l, &r, sc); Typed::I64(v) }
                "//" => { let v = b.py_floordiv(&l, &r, sc); Typed::I64(v) }
                "/" => {
                    // int / int is Python float division: sitofp both,
                    // zero check, fdiv
                    b.fzero_check(&r, sc);
                    let lf = to_f64_ref(b, &l);
                    let rf = to_f64_ref(b, &r);
                    let d = b.nx();
                    b.line(format!("  %\"{}\" = fdiv double {}, {}", d, lf, rf));
                    Typed::F64(format!("%\"{}\"", d))
                }
                _ => bail("op"),
            }
        }
        _ => bail("eval expr"),
    }
}

fn to_f64(b: &mut FnB, t: Typed) -> String {
    match t {
        Typed::F64(s) => s,
        Typed::I64(s) => to_f64_ref(b, &s),
        Typed::Str(_) => bail("str where float expected"),
    }
}

fn to_f64_ref(b: &mut FnB, i64_ref: &str) -> String {
    let v = b.nx();
    b.line(format!("  %\"{}\" = sitofp i64 {} to double", v, i64_ref));
    format!("%\"{}\"", v)
}


// generic multi-arg print: per arg, eval then printf, " " between
// args, "\n" at the end; int -> %lld, float -> float_repr %s,
// str const -> %.*s with (len, gep) pair
fn conv_print(b: &mut FnB, st: &Val, sc: &mut usize) {
    let fslots = F_SLOTS.with(|f| f.borrow().clone());
    let args = st.get(2).items();
    if args.is_empty() { bail("print arity"); }
    let n_args = args.len();
    for (ai, a) in args.iter().enumerate() {
        if a.head() == "const" && matches!(a.get(1), Val::Str(_)) {
            let text = a.get(1).str_of();
            let blen = text.chars().count();
            let gname = add_str(sc, &text);
            let g = b.nx();
            b.line(format!(
                "  %\"{}\" = getelementptr [{} x i8], [{} x i8]* @\"{}\", i32 0, i32 0",
                g, blen + 1, blen + 1, gname));
            let fmt = add_str(sc, "%.*s");
            let fg = b.nx();
            b.line(format!(
                "  %\"{}\" = getelementptr [5 x i8], [5 x i8]* @\"{}\", i32 0, i32 0",
                fg, fmt));
            let p = b.nx();
            b.line(format!(
                "  %\"{}\" = call i32 (i8*, ...) @\"printf\"(i8* %\"{}\", i64 {}, i8* %\"{}\")",
                p, fg, blen, g));
        } else {
            let v_typed = eval_mod(b, a, &fslots, sc);
            match v_typed {
                Typed::I64(v) => {
                    let fmt = add_str(sc, "%lld");
                    let g = b.nx();
                    b.line(format!(
                        "  %\"{}\" = getelementptr [5 x i8], [5 x i8]* @\"{}\", i32 0, i32 0",
                        g, fmt));
                    let p = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i32 (i8*, ...) @\"printf\"(i8* %\"{}\", i64 {})",
                        p, g, v));
                }
                Typed::F64(_) => {
                    let r = to_f64(b, v_typed);
                    let cr = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i8* @\"float_repr\"(double {})", cr, r));
                    let fmt = add_str(sc, "%s");
                    let g = b.nx();
                    b.line(format!(
                        "  %\"{}\" = getelementptr [3 x i8], [3 x i8]* @\"{}\", i32 0, i32 0",
                        g, fmt));
                    let p = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i32 (i8*, ...) @\"printf\"(i8* %\"{}\", i8* %\"{}\")",
                        p, g, cr));
                }
                Typed::Str(_) => bail("print str arg"),
            }
        }
        if ai + 1 < n_args {
            let sep = add_str(sc, " ");
            let g = b.nx();
            b.line(format!(
                "  %\"{}\" = getelementptr [2 x i8], [2 x i8]* @\"{}\", i32 0, i32 0",
                g, sep));
            let p = b.nx();
            b.line(format!(
                "  %\"{}\" = call i32 (i8*, ...) @\"printf\"(i8* %\"{}\")", p, g));
        }
    }
    let nl = add_str(sc, "\x0a");
    let g2 = b.nx();
    b.line(format!(
        "  %\"{}\" = getelementptr [2 x i8], [2 x i8]* @\"{}\", i32 0, i32 0",
        g2, nl));
    let p2 = b.nx();
    b.line(format!(
        "  %\"{}\" = call i32 (i8*, ...) @\"printf\"(i8* %\"{}\")", p2, g2));
}

fn eval_mod(b: &mut FnB, e: &Val, fslots: &[String], sc: &mut usize) -> Typed {
    if e.head() == "name" {
        let n = e.get(1).str_of();
        let l = b.nx();
        if STR_SLOTS.with(|s| s.borrow().iter().any(|f| f == &n)) {
            b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, n));
            return Typed::Str(format!("%\"{}\"", l));
        }
        if fslots.iter().any(|f| f == &n) {
            b.line(format!("  %\"{}\" = load double, double* @\"{}\"", l, n));
            return Typed::F64(format!("%\"{}\"", l));
        }
        b.line(format!("  %\"{}\" = load i64, i64* @\"{}\"", l, n));
        return Typed::I64(format!("%\"{}\"", l));
    }
    if e.head() == "call" && e.get(1).head() == "name"
        && e.get(1).get(1).str_of() == "len" {
        let ia = e.get(2).items();
        if ia.len() != 1 || ia[0].head() != "name" { bail("len arg"); }
        let n = ia[0].get(1).str_of();
        if LST_SLOTS.with(|s| s.borrow().iter().any(|f| f == &n)) {
            let l = b.nx();
            b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, n));
            let c = b.nx();
            b.line(format!(
                "  %\"{}\" = call i64 @\"rawlist_len\"(i8* %\"{}\")", c, l));
            return Typed::I64(format!("%\"{}\"", c));
        }
        if DCT_SLOTS.with(|s| s.borrow().iter().any(|f| f == &n)) {
            let l = b.nx();
            b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, n));
            let bc = b.nx();
            b.line(format!(
                "  %\"{}\" = bitcast i8* %\"{}\" to {{i64, i64, i64, i64, i64*, i64*, i64*}}*",
                bc, l));
            let gp = b.nx();
            b.line(format!(
                "  %\"{}\" = getelementptr {{i64, i64, i64, i64, i64*, i64*, i64*}}, {{i64, i64, i64, i64, i64*, i64*, i64*}}* %\"{}\", i32 0, i32 0",
                gp, bc));
            let ld = b.nx();
            b.line(format!("  %\"{}\" = load i64, i64* %\"{}\"", ld, gp));
            return Typed::I64(format!("%\"{}\"", ld));
        }
        if STR_SLOTS.with(|s| s.borrow().iter().any(|f| f == &n)) {
            let l = b.nx();
            b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, n));
            let bc = b.nx();
            b.line(format!(
                "  %\"{}\" = bitcast i8* %\"{}\" to {{i64, i64, i8*, i64}}*", bc, l));
            let gp = b.nx();
            b.line(format!(
                "  %\"{}\" = getelementptr {{i64, i64, i8*, i64}}, {{i64, i64, i8*, i64}}* %\"{}\", i32 0, i32 3",
                gp, bc));
            let ld = b.nx();
            b.line(format!("  %\"{}\" = load i64, i64* %\"{}\"", ld, gp));
            return Typed::I64(format!("%\"{}\"", ld));
        }
        bail("len target");
    }
    if e.head() == "call" && e.get(1).head() == "name"
        && e.get(1).get(1).str_of() != "len" {
        // user call with general args (const/name/expr), left to right
        let fname = e.get(1).get(1).str_of();
        let args = e.get(2).items();
        let mut parts = Vec::new();
        for a in args.iter() {
            let v = eval_expr(b, a,
                &|n: &str| format!("@\"{}\"", n),
                &|n: &str| format!("@\"{}\"", n), sc, fslots);
            match v {
                Typed::I64(r) => parts.push(format!("i64 {}", r)),
                _ => bail("call arg type"),
            }
        }
        let c = b.nx();
        b.line(format!("  %\"{}\" = call i64 @\"{}\"({})",
            c, fname, parts.join(", ")));
        return Typed::I64(format!("%\"{}\"", c));
    }
    eval_expr(b, e,
        &|n: &str| format!("@\"{}\"", n),
        &|n: &str| format!("@\"{}\"", n), sc, fslots)
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("usage: silu-conv <file.si>");
        std::process::exit(2);
    }
    let path = &args[1];
    let exe = env::current_exe().unwrap();
    let fe = exe.parent().unwrap().join("silu-fe");
    let ir = Command::new(fe).arg(path).output().expect("silu-fe missing");
    if !ir.status.success() {
        std::io::stderr().write_all(&ir.stderr).unwrap();
        std::process::exit(1);
    }
    let module = parse_json(&String::from_utf8_lossy(&ir.stdout));
    let stmts = module.get(1).items();

    let mut sc = STR_BASE;
    let func_defs = walk_module(&stmts, &mut sc);

    let mut out = String::new();
    out.push_str(CONST_PREFIX);
    for fd in &func_defs {
        out.push_str(&convert_func(fd, &mut sc));
    }
    unsafe {
        out.push_str(MAIN_OUT.as_ref().unwrap());
    }
    // tail globals: strict creation order (strings and vars interleaved)
    TAIL.with(|t| {
        let all = t.borrow();
        let last = all.len();
        for (i, line) in all.iter().enumerate() {
            out.push_str(line);
            if i + 1 < last { out.push('\n'); }
        }
    });
    let so = std::io::stdout();
    let mut lock = so.lock();
    let _ = lock.write_all(out.as_bytes());
}
