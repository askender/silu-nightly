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
    static STRS: RefCell<Vec<String>> = RefCell::new(Vec::new());
}

fn add_str(counter: &mut usize, text: &str) -> String {
    let name = format!("str_{}", counter);
    *counter += 1;
    let bytes = format!("{}\x00", text);
    STRS.with(|s| s.borrow_mut().push(format!(
        "@\"{}\" = constant [{} x i8] c\"{}\"",
        name, bytes.len(), escape_bytes(bytes.as_bytes()))));
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
}

enum Slot { Global(String) } // @"name" variables (module scope)

impl FnB {
    fn new(anon_start: usize) -> FnB {
        FnB { blocks: vec![("entry".into(), Vec::new())], cur: 0, anon: anon_start }
    }
    fn add_block(&mut self, label: &str) -> usize {
        self.blocks.push((label.to_string(), Vec::new()));
        self.blocks.len() - 1
    }
    fn pos(&mut self, i: usize) { self.cur = i; }
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
    // i64 value expression in the CURRENT block against a variable slot
    // kind (global @"x" or local %"x")
    fn expr_i64(&mut self, e: &Val, slot_ref: &dyn Fn(&str) -> String) -> String {
        match e.head() {
            "name" => {
                let l = self.nx();
                let var = slot_ref(&e.get(1).str_of());
                self.line(format!("  %\"{}\" = load i64, i64* {}", l, var));
                format!("%\"{}\"", l)
            }
            "const" if matches!(e.get(1), Val::Int(_)) => e.get(1).int_of().to_string(),
            "%" => {
                let a = self.expr_i64(&e.get(1), slot_ref);
                let b = self.expr_i64(&e.get(2), slot_ref);
                self.py_mod(&a, &b, unsafe { &mut *SC_PTR })
            }
            "//" => {
                let a = self.expr_i64(&e.get(1), slot_ref);
                let b = self.expr_i64(&e.get(2), slot_ref);
                self.py_floordiv(&a, &b, unsafe { &mut *SC_PTR })
            }
            _ => bail("expr"),
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

// module-level walk (main body). Returns (fn_defs, module_globals).
fn walk_module(stmts: &[Val], sc: &mut usize)
              -> (Vec<Val>, Vec<String>, String) {
    let mut b = FnB::new(1); // .1 = main ret slot
    let mut func_defs: Vec<Val> = Vec::new();
    let mut module_globals: Vec<String> = Vec::new();
    let mut fslots: Vec<String> = Vec::new(); // float-typed global names

    let mut i = 0usize;
    while i < stmts.len() {
        let st = stmts[i].clone();
        if !matches!(st, Val::List(_)) { i += 1; continue; }
        match st.head() {
            "line" => { b.line_store(st.get(1).int_of()); }
            "ann_assign" => {
                *sc += 1; // module binding consumes a string slot
                let name = st.get(1).str_of();
                let init = st.get(2);
                let anno = st.get(3).get(1).str_of();
                if anno == "float" {
                    fslots.push(name.clone());
                    if !matches!(init.get(1), Val::Float(_)) || init.head() != "const" {
                        bail("float init");
                    }
                    let f = match &init.items()[1] { Val::Float(v) => *v, _ => 0.0 };
                    module_globals.push(format!("@\"{}\" = global double {}",
                                                name, double_bits(f)));
                    b.silent();
                    b.line(format!("  store double {}, double* @\"{}\"",
                                   double_bits(f), name));
                } else {
                    if !matches!(init.get(1), Val::Int(_)) || init.head() != "const" {
                        bail("ann_assign init");
                    }
                    module_globals.push(format!("@\"{}\" = global i64 0", name));
                    b.silent();
                    b.line(format!("  store i64 {}, i64* @\"{}\"",
                                   init.get(1).int_of(), name));
                }
            }
            "while" => {
                let cond = st.get(1);
                let body = st.get(2).items();
                // create cond/body/end blocks (creation order = output)
                let cond_b = b.add_block("while_cond");
                let body_b = b.add_block("while_body");
                let end_b = b.add_block("while_end");
                b.silent();
                b.line("  br label %\"while_cond\"".into());
                b.pos(cond_b);
                let pred = match cond.head() {
                    "<" => "slt", "<=" => "sle", ">" => "sgt", ">=" => "sge",
                    _ => bail("while cond op"),
                };
                let lhs = eval_mod(&mut b, &cond.get(1), &fslots, sc);
                let rhs = eval_mod(&mut b, &cond.get(2), &fslots, sc);
                let ic = b.nx();
                // float compare: fcmp olt (Python <)
                if matches!(lhs, Typed::F64(_)) {
                    let l = to_f64(&mut b, lhs);
                    let r = to_f64(&mut b, rhs);
                    let fp = match pred { "slt" => "olt", "sle" => "ole",
                                         "sgt" => "ogt", _ => "oge" };
                    b.line(format!("  %\"{}\" = fcmp {} double {}, {}", ic, fp, l, r));
                } else {
                    let (Typed::I64(l), Typed::I64(r)) = (lhs, rhs) else {
                        bail("cond types") };
                    b.line(format!("  %\"{}\" = icmp {} i64 {}, {}", ic, pred, l, r));
                }
                b.silent();
                b.line(format!(
                    "  br i1 %\"{}\", label %\"while_body\", label %\"while_end\"", ic));
                b.pos(body_b);
                // body statements flow through; checked ops move cur
                let mut j = 0usize;
                while j < body.len() {
                    let s = body[j].clone();
                    if s.head() == "line" {
                        b.line_store(s.get(1).int_of());
                        j += 1;
                        continue;
                    }
                    if s.head() == "aug_assign" {
                        conv_aug_assign(&mut b, &s, sc, &global_slot);
                        j += 1;
                        continue;
                    }
                    if s.head() == "assign" {
                        let name = s.get(1).str_of();
                        if fslots.iter().any(|f| f == &name) {
                            let v = eval_mod(&mut b, &s.get(2), &fslots, sc);
                            let r = to_f64(&mut b, v);
                            b.silent();
                            b.line(format!("  store double {}, double* @\"{}\"", r, name));
                            j += 1;
                            continue;
                        }
                        bail("int assign in body");
                    }
                    bail("while body stmt");
                }
                b.silent();
                b.line("  br label %\"while_cond\"".into());
                b.pos(end_b);
            }
            "func_def" => {
                *sc += 1;
                func_defs.push(st.clone());
            }
            "call" if st.get(1).head() == "name"
                     && st.get(1).get(1).str_of() == "print" => {
                let args = st.get(2).items();
                if args.len() != 1 { bail("print arity"); }
                let a = &args[0];
                let v_typed = eval_mod(&mut b, a, &fslots, sc);
                if matches!(v_typed, Typed::F64(_)) {
                    let r = to_f64(&mut b, v_typed);
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
                    let nl = add_str(sc, "\x0a");
                    let g2 = b.nx();
                    b.line(format!(
                        "  %\"{}\" = getelementptr [2 x i8], [2 x i8]* @\"{}\", i32 0, i32 0",
                        g2, nl));
                    let p2 = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i32 (i8*, ...) @\"printf\"(i8* %\"{}\")", p2, g2));
                    i += 1;
                    continue;
                }
                let Typed::I64(v) = v_typed else { bail("print type") };
                let fmt = add_str(sc, "%lld");
                let g = b.nx();
                b.line(format!(
                    "  %\"{}\" = getelementptr [5 x i8], [5 x i8]* @\"{}\", i32 0, i32 0",
                    g, fmt));
                let p = b.nx();
                b.line(format!(
                    "  %\"{}\" = call i32 (i8*, ...) @\"printf\"(i8* %\"{}\", i64 {})",
                    p, g, v));
                let nl = add_str(sc, "\x0a");
                let g2 = b.nx();
                b.line(format!(
                    "  %\"{}\" = getelementptr [2 x i8], [2 x i8]* @\"{}\", i32 0, i32 0",
                    g2, nl));
                let p2 = b.nx();
                b.line(format!(
                    "  %\"{}\" = call i32 (i8*, ...) @\"printf\"(i8* %\"{}\")", p2, g2));
            }
            _ => bail(st.head()),
        }
        i += 1;
    }
    b.silent(); // ret
    b.line("  ret i32 0".into());
    unsafe {
        MAIN_OUT = Some(b.render("define i32 @\"main\"()\n"));
    }
    (func_defs, module_globals, String::new())
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
                    if s.head() == "return" && s.get(1).head() == "name" {
                        let l = b.nx();
                        b.line(format!("  %\"{}\" = load i64, i64* %\"{}\"",
                                       l, s.get(1).get(1).str_of()));
                        b.silent();
                        b.line(format!("  ret i64 %\"{}\"", l));
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
                let v = st.get(1);
                match v.head() {
                    "name" => {
                        let l = b.nx();
                        b.line(format!("  %\"{}\" = load i64, i64* %\"{}\"",
                                       l, v.get(1).str_of()));
                        b.silent();
                        b.line(format!("  ret i64 %\"{}\"", l));
                    }
                    "+" => {
                        let lhs_e = v.get(1);
                        let rhs_e = v.get(2);
                        // lhs may be a call, rhs a checked sub or const
                        let lhs = match lhs_e.head() {
                            "call" => conv_call(&mut b, &lhs_e, sc),
                            "name" => {
                                let l = b.nx();
                                b.line(format!("  %\"{}\" = load i64, i64* %\"{}\"",
                                               l, lhs_e.get(1).str_of()));
                                format!("%\"{}\"", l)
                            }
                            _ => bail("ret lhs"),
                        };
                        let rhs = match rhs_e.head() {
                            "call" => conv_call(&mut b, &rhs_e, sc),
                            "-" => {
                                let a = expr_sub(&mut b, &rhs_e, sc);
                                a
                            }
                            "const" if matches!(rhs_e.get(1), Val::Int(_)) =>
                                rhs_e.get(1).int_of().to_string(),
                            _ => bail("ret rhs"),
                        };
                        let res = b.checked_raw(&lhs, &rhs, "+", sc);
                        b.silent();
                        b.line(format!("  ret i64 {}", res));
                    }
                    _ => bail("return expr"),
                }
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
enum Typed { I64(String), F64(String) }

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
            let _ = slot_f;
            if fslots.iter().any(|f| f == &n) {
                b.line(format!("  %\"{}\" = load double, double* @\"{}\"", l, n));
                return Typed::F64(format!("%\"{}\"", l));
            }
            b.line(format!("  %\"{}\" = load i64, i64* @\"{}\"", l, n));
            Typed::I64(format!("%\"{}\"", l))
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
    }
}

fn to_f64_ref(b: &mut FnB, i64_ref: &str) -> String {
    let v = b.nx();
    b.line(format!("  %\"{}\" = sitofp i64 {} to double", v, i64_ref));
    format!("%\"{}\"", v)
}


fn eval_mod(b: &mut FnB, e: &Val, fslots: &[String], sc: &mut usize) -> Typed {
    if e.head() == "name" {
        let n = e.get(1).str_of();
        let l = b.nx();
        if fslots.iter().any(|f| f == &n) {
            b.line(format!("  %\"{}\" = load double, double* @\"{}\"", l, n));
            return Typed::F64(format!("%\"{}\"", l));
        }
        b.line(format!("  %\"{}\" = load i64, i64* @\"{}\"", l, n));
        return Typed::I64(format!("%\"{}\"", l));
    }
    if e.head() == "call" {
        let ia = e.get(2).items();
        if ia.len() != 1 || ia[0].head() != "const"
            || !matches!(ia[0].get(1), Val::Int(_)) {
            bail("print arg");
        }
        let c = b.nx();
        b.line(format!("  %\"{}\" = call i64 @\"{}\"(i64 {})",
            c, e.get(1).get(1).str_of(), ia[0].get(1).int_of()));
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
    let (func_defs, module_globals, _fs) = walk_module(&stmts, &mut sc);

    let mut out = String::new();
    out.push_str(CONST_PREFIX);
    for fd in &func_defs {
        out.push_str(&convert_func(fd, &mut sc));
    }
    unsafe {
        out.push_str(MAIN_OUT.as_ref().unwrap());
    }
    // tail globals: module vars first, strings in creation order
    let mut tail: Vec<String> = module_globals.clone();
    STRS.with(|s| tail.extend(s.borrow().iter().cloned()));
    let last = tail.len();
    for (i, line) in tail.iter().enumerate() {
        out.push_str(line);
        if i + 1 < last { out.push('\n'); }
    }
    let so = std::io::stdout();
    let mut lock = so.lock();
    let _ = lock.write_all(out.as_bytes());
}
