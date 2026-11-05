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
const TAGGED_PREFIX: &str = include_str!("../../tagged_prefix.ll");
const STR_BASE: usize = 297; // runtime consumed 0..=296 (see README)
// the tagged/Json runtime block adds 15 module globals (14 fns + the
// json_typeerr constant), shifting every user string's number by 15
const TAGGED_SLOTS: usize = 15;

#[derive(Clone, Debug, PartialEq)]
enum Val { Null, Bool(bool), Int(i64), Float(f64), Str(String), List(Vec<Val>) }

impl Val {
    fn head(&self) -> &str {
        match self {
            Val::List(v) => match v.first() {
                Some(Val::Str(s)) => s, _ => "" },
            _ => "" }
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
    // function-body context: local typed names, hoisted allocas
    // (first-appearance order, params first), return type, signatures
    static FN_I: RefCell<Vec<String>> = RefCell::new(Vec::new());
    static FN_F: RefCell<Vec<String>> = RefCell::new(Vec::new());
    static FN_ALLOCAS: RefCell<Vec<(String, String)>> = RefCell::new(Vec::new());
    static FN_PARAMS: RefCell<Vec<(String, String)>> = RefCell::new(Vec::new());
    static FN_L: RefCell<Vec<(String, String)>> = RefCell::new(Vec::new());
    static FN_PY: RefCell<Vec<String>> = RefCell::new(Vec::new());
    static FN_D: RefCell<Vec<String>> = RefCell::new(Vec::new());
    static JSON_SLOTS: RefCell<Vec<String>> = RefCell::new(Vec::new());
    static IN_FN: RefCell<bool> = RefCell::new(false);
    static FN_RET: RefCell<String> = RefCell::new(String::new());
    static LST_ELEM: RefCell<Vec<(String, String)>> = RefCell::new(Vec::new());
    static FN_SIGS: RefCell<Vec<(String, Vec<String>, String)>> =
        RefCell::new(Vec::new()); // (name, arg types, ret type)
}

fn enum_val(enum_: &str, variant: &str) -> Option<i64> {
    ENUMS.with(|m| m.borrow().iter().find(|(k, _)| k == enum_).and_then(
        |(_, vs)| vs.iter().position(|v| v == variant).map(|i| i as i64)))
}

fn class_fields(cls: &str) -> Option<Vec<(String, String)>> {
    CLASSES.with(|c| c.borrow().iter().find(|(k, _)| k == cls)
        .map(|(_, fs)| fs.clone()))
}

fn is_local_s(n: &str) -> bool {
    FN_S.with(|t| t.borrow().iter().any(|x| x == n))
}

fn fn_ty_of(n: &str) -> Option<String> {
    FN_TY.with(|t| t.borrow().iter().find(|(k, _)| k == n)
        .map(|(_, v)| v.clone()))
}

fn is_class(n: &str) -> bool {
    CLASSES.with(|c| c.borrow().iter().any(|(k, _)| k == n))
}

fn is_enum(n: &str) -> bool {
    ENUMS.with(|m| m.borrow().iter().any(|(k, _)| k == n))
}

// field LLVM type from its annotation
fn field_ll_ty(t: &str) -> &'static str {
    match t { "float" => "double", _ => "i64" } // int/Tok/instance/str-ptr slots
}

fn tv_valtype(tv: &Val) -> String {
    match tv { Val::List(vs) =>
        vs.first().map(|v| v.get(1).str_of()).unwrap_or_else(|| "int".into()),
        _ => "int".into() }
}

fn dct_key_ty(n: &str) -> String {
    DCT_KEYS.with(|m| m.borrow().iter()
        .find(|(k, _)| k == n).map(|(_, v)| v.clone())
        .unwrap_or_else(|| "int".into()))
}

fn lst_elem_ty(n: &str) -> String {
    if let Some(t) = FN_L.with(|m| m.borrow().iter()
            .find(|(k, _)| k == n).map(|(_, v)| v.clone())) { return t; }
    LST_ELEM.with(|m| m.borrow().iter()
        .find(|(k, _)| k == n).map(|(_, v)| v.clone())
        .unwrap_or_else(|| "int".into()))
}

// dict value annotation is Json? (dict[str,Json] evidence)
fn dct_val_is_json(n: &str) -> bool {
    DCT_VALS.with(|m| m.borrow().iter()
        .any(|(k, v)| k == n && v == "Json"))
}

// container slot: local alloca %x vs module global @x
fn lst_slot(n: &str) -> String {
    if FN_L.with(|m| m.borrow().iter().any(|(k, _)| k == n)) {
        format!("%\"{}\"", n)
    } else { format!("@\"{}\"", n) }
}

// pyobj locals ({i32,i8*}* alloca) vs module pyobj globals
fn py_slot(n: &str) -> String {
    if FN_PY.with(|m| m.borrow().iter().any(|k| k == n)) {
        format!("%\"{}\"", n)
    } else { format!("@\"{}\"", n) }
}

// dict local alloca %x vs module global @x (function-local dict[str,Json])
fn dct_slot(n: &str) -> String {
    if FN_D.with(|m| m.borrow().iter().any(|k| k == n)) {
        format!("%\"{}\"", n)
    } else { format!("@\"{}\"", n) }
}

// name resolution: function locals shadow module globals
fn is_local_f(n: &str) -> bool {
    FN_F.with(|f| f.borrow().iter().any(|x| x == n))
}
fn is_local_i(n: &str) -> bool {
    FN_I.with(|f| f.borrow().iter().any(|x| x == n))
}

fn is_dyn_class(c: &str) -> bool {
    DYN_CLASSES.with(|d| d.borrow().iter().any(|x| x == c))
}

fn class_cid(c: &str) -> i64 {
    CLASSES.with(|c2| c2.borrow().iter().position(|(k, _)| k == c)
        .map(|i| (i + 1) as i64).unwrap_or(0))
}

fn is_py(n: &str) -> bool {
    PY_SLOTS.with(|t| t.borrow().iter().any(|x| x == n))
}

fn is_local_b(n: &str) -> bool {
    FN_B.with(|t| t.borrow().iter().any(|x| x == n))
}

fn inst_stor(n: &str) -> Option<String> {
    FN_STOR.with(|t| t.borrow().iter().find(|(k, _)| k == n)
        .map(|(_, v)| v.clone()))
}

thread_local! {
    // tail globals in strict CREATION order: strings and module var
    // declarations interleave as they are first emitted (list.si find)
    static TAIL: RefCell<Vec<String>> = RefCell::new(Vec::new());
    static STR_SLOTS: RefCell<Vec<String>> = RefCell::new(Vec::new());
    static LST_SLOTS: RefCell<Vec<String>> = RefCell::new(Vec::new()); // list-typed globals
    static DCT_SLOTS: RefCell<Vec<String>> = RefCell::new(Vec::new()); // dict-typed globals
    static DCT_KEYS: RefCell<Vec<(String, String)>> = RefCell::new(Vec::new()); // dict key types
    static DCT_VALS: RefCell<Vec<(String, String)>> = RefCell::new(Vec::new()); // dict value types
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
    fn list_get(&mut self, objref: &str, idx: &str, sc: &mut usize,
                elem: &str) -> String {
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
        if elem == "float" {
            let fb = self.nx();
            self.line(format!(
                "  %\"{}\" = bitcast i64 %\"{}\" to double", fb, ld));
            return format!("%\"{}\"", fb);
        }
        format!("%\"{}\"", ld)
    }

    // complete a paused view conversion: extract x2 + str_view stores
    // + unused bitcast (jsonparse compare interleave, second half)
    fn finish_view_split(&mut self, pair: &str) {
        let ev1 = self.nx();
        self.line(format!(
            "  %\"{}\" = extractvalue {{i8*, i64}} {}, 0", ev1, pair));
        let ev2 = self.nx();
        self.line(format!(
            "  %\"{}\" = extractvalue {{i8*, i64}} {}, 1", ev2, pair));
        let vn = self.uniq_label("str_view");
        self.reg_names.push(vn.clone());
        if IN_FN.with(|v| *v.borrow()) {
            FN_ALLOCAS.with(|f| f.borrow_mut()
                .push((vn.clone(), "view".into())));
        } else {
            MAIN_ALLOCAS.with(|m| m.borrow_mut().push(vn.clone()));
        }
        for fld in [0u32, 1, 3] {
            let g = self.nx();
            self.line(format!(
                "  %\"{}\" = getelementptr {{i64, i64, i8*, i64}}, {{i64, i64, i8*, i64}}* %\"{}\", i32 0, i32 {}",
                g, vn, fld));
            self.silent();
            self.line(format!(
                "  store i64 %\"{}\", i64* %\"{}\"", ev2, g));
        }
        let g2 = self.nx();
        self.line(format!(
            "  %\"{}\" = getelementptr {{i64, i64, i8*, i64}}, {{i64, i64, i8*, i64}}* %\"{}\", i32 0, i32 2",
            g2, vn));
        self.silent();
        self.line(format!(
            "  store i8* %\"{}\", i8** %\"{}\"", ev1, g2));
        let vbc = self.nx();
        self.line(format!(
            "  %\"{}\" = bitcast {{i64, i64, i8*, i64}}* %\"{}\" to i8*",
            vbc, vn));
    }

    // list element WRITE: bounds-check chain + store. objref/keyref/valref
    // are ready (caller ordered: obj, key, value); cursor continues in
    // set_ok. Fresh IndexError string per write (47B variant).
    fn list_set(&mut self, objref: &str, key: &str, val: &str, sc: &mut usize,
                elem: &str) {
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
        // float values bitcast BEFORE the gep (nbody set_ok evidence)
        let vref = if elem == "float" {
            let fb = self.nx();
            self.line(format!(
                "  %\"{}\" = bitcast double {} to i64", fb, val));
            format!("%\"{}\"", fb)
        } else { val.to_string() };
        let gep = self.nx();
        self.line(format!(
            "  %\"{}\" = getelementptr i64, i64* %\"{}\", i64 %\"{}\"", gep, dbc, sel));
        self.silent();
        self.line(format!("  store i64 {}, i64* %\"{}\"", vref, gep));
    }

    // str char index s[i]: cv machinery (bounds pair + ascii/walk + phi
    // + utf8 width selects + rawstr_char1) -> 1-char str (calc blueprint 5)
    fn str_char_at(&mut self, objref: &str, idx: &str, sc: &mut usize) -> String {
        let v = COMPARE_VIEW.with(|c| *c.borrow());
        self.str_char_at_mode(objref, idx, sc, v)
    }
    // view=true: compare-context char reads store the pair into a hoisted
    // str_view (dead chain) instead of calling rawstr_char1 (jsonparse)
    fn str_char_at_mode(&mut self, objref: &str, idx: &str, sc: &mut usize,
                        view: bool) -> String {
        let bc = self.nx();
        self.line(format!(
            "  %\"{}\" = bitcast i8* {} to {{i64, i64, i8*, i64}}*",
            bc, objref));
        let g3 = self.nx();
        self.line(format!(
            "  %\"{}\" = getelementptr {{i64, i64, i8*, i64}}, {{i64, i64, i8*, i64}}* %\"{}\", i32 0, i32 3",
            g3, bc));
        let len = self.nx();
        self.line(format!(
            "  %\"{}\" = load i64, i64* %\"{}\"", len, g3));
        let g0 = self.nx();
        self.line(format!(
            "  %\"{}\" = getelementptr {{i64, i64, i8*, i64}}, {{i64, i64, i8*, i64}}* %\"{}\", i32 0, i32 0",
            g0, bc));
        let cap = self.nx();
        self.line(format!(
            "  %\"{}\" = load i64, i64* %\"{}\"", cap, g0));
        let g2 = self.nx();
        self.line(format!(
            "  %\"{}\" = getelementptr {{i64, i64, i8*, i64}}, {{i64, i64, i8*, i64}}* %\"{}\", i32 0, i32 2",
            g2, bc));
        let chars = self.nx();
        self.line(format!(
            "  %\"{}\" = load i8*, i8** %\"{}\"", chars, g2));
        let neg = self.nx();
        self.line(format!(
            "  %\"{}\" = icmp slt i64 {}, 0", neg, idx));
        let sum = self.nx();
        self.line(format!(
            "  %\"{}\" = add i64 {}, %\"{}\"", sum, idx, len));
        let adj = self.nx();
        self.line(format!(
            "  %\"{}\" = select  i1 %\"{}\", i64 %\"{}\", i64 {}",
            adj, neg, sum, idx));
        let ge = self.nx();
        self.line(format!(
            "  %\"{}\" = icmp sge i64 %\"{}\", 0", ge, adj));
        let lt = self.nx();
        self.line(format!(
            "  %\"{}\" = icmp slt i64 %\"{}\", %\"{}\"", lt, adj, len));
        let both = self.nx();
        self.line(format!(
            "  %\"{}\" = and i1 %\"{}\", %\"{}\"", both, ge, lt));
        let ok_lbl = self.uniq_label("cv_ok");
        let err_lbl = self.uniq_label("cv_err");
        self.silent();
        self.line(format!(
            "  br i1 %\"{}\", label %\"{}\", label %\"{}\"",
            both, ok_lbl, err_lbl));
        let ob = self.add_block(&ok_lbl);
        self.pos(ob);
        let eb = self.add_block(&err_lbl);
        // cv_err SHARES its panic string across all char-index sites
        let cached = CV_ERR_NAME.with(|c| c.borrow().clone());
        let name = match cached {
            Some(n) => n,
            None => {
                let n = add_str(sc, "IndexError: string index out of range");
                CV_ERR_NAME.with(|c| *c.borrow_mut() = Some(n.clone()));
                n
            }
        };
        let g = self.nx();
        self.blocks[eb].1.push(format!(
            "  %\"{}\" = getelementptr [38 x i8], [38 x i8]* @\"{}\", i32 0, i32 0",
            g, name));
        self.silent();
        self.blocks[eb].1.push(format!(
            "  call void @\"silu_panic\"(i8* %\"{}\")", g));
        self.silent();
        self.blocks[eb].1.push("  unreachable".into());
        // in cv_ok: ascii? check
        let eqc = self.nx();
        self.line(format!(
            "  %\"{}\" = icmp eq i64 %\"{}\", %\"{}\"", eqc, cap, len));
        let a_lbl = self.uniq_label("cv_ascii");
        let w_lbl = self.uniq_label("cv_walk");
        self.silent();
        self.line(format!(
            "  br i1 %\"{}\", label %\"{}\", label %\"{}\"",
            eqc, a_lbl, w_lbl));
        let ab = self.add_block(&a_lbl);
        let wb = self.add_block(&w_lbl);
        let j_lbl = self.uniq_label("cv_join");
        self.pos(ab);
        self.silent();
        self.line(format!("  br label %\"{}\"", j_lbl));
        self.pos(wb);
        let off = self.nx();
        self.line(format!(
            "  %\"{}\" = call i64 @\"rawutf8_cp_offset\"(i8* %\"{}\", i64 %\"{}\")",
            off, chars, adj));
        self.silent();
        self.line(format!("  br label %\"{}\"", j_lbl));
        let jb = self.add_block(&j_lbl);
        self.pos(jb);
        let ph = self.nx();
        self.line(format!(
            "  %\"{}\" = phi  i64 [%\"{}\", %\"{}\"], [%\"{}\", %\"{}\"]",
            ph, adj, a_lbl, off, w_lbl));
        let cp = self.nx();
        self.line(format!(
            "  %\"{}\" = getelementptr i8, i8* %\"{}\", i64 %\"{}\"", cp, chars, ph));
        let ld = self.nx();
        self.line(format!(
            "  %\"{}\" = load i8, i8* %\"{}\"", ld, cp));
        let a1 = self.nx();
        self.line(format!(
            "  %\"{}\" = and i8 %\"{}\", 224", a1, ld));
        let c1 = self.nx();
        self.line(format!(
            "  %\"{}\" = icmp eq i8 %\"{}\", 192", c1, a1));
        let a2 = self.nx();
        self.line(format!(
            "  %\"{}\" = and i8 %\"{}\", 240", a2, ld));
        let c2 = self.nx();
        self.line(format!(
            "  %\"{}\" = icmp eq i8 %\"{}\", 224", c2, a2));
        let a3 = self.nx();
        self.line(format!(
            "  %\"{}\" = and i8 %\"{}\", 248", a3, ld));
        let c3 = self.nx();
        self.line(format!(
            "  %\"{}\" = icmp eq i8 %\"{}\", 240", c3, a3));
        let s1 = self.nx();
        self.line(format!(
            "  %\"{}\" = select  i1 %\"{}\", i64 4, i64 1", s1, c3));
        let s2 = self.nx();
        self.line(format!(
            "  %\"{}\" = select  i1 %\"{}\", i64 3, i64 %\"{}\"", s2, c2, s1));
        let s3 = self.nx();
        self.line(format!(
            "  %\"{}\" = select  i1 %\"{}\", i64 2, i64 %\"{}\"", s3, c1, s2));
        let s4 = self.nx();
        self.line(format!(
            "  %\"{}\" = select  i1 %\"{}\", i64 1, i64 %\"{}\"", s4, eqc, s3));
        let gp = self.nx();
        self.line(format!(
            "  %\"{}\" = getelementptr i8, i8* %\"{}\", i64 %\"{}\"", gp, chars, ph));
        let iv1 = self.nx();
        self.line(format!(
            "  %\"{}\" = insertvalue {{i8*, i64}} undef, i8* %\"{}\", 0", iv1, gp));
        let iv2 = self.nx();
        self.line(format!(
            "  %\"{}\" = insertvalue {{i8*, i64}} %\"{}\", i64 %\"{}\", 1", iv2, iv1, s4));
        // interleaved order: the rhs const's gep+create_str sits
        // BETWEEN insertvalue and extractvalue (jsonparse .100-.103).
        // Pause right after the pair when a pending marker is requested.
        if view && PENDING_PAIR.with(|c| c.borrow().is_some()) {
            PENDING_PAIR.with(|c| *c.borrow_mut() =
                Some(format!("%\"{}\"", iv2)));
            return format!("%\"{}\"", iv2);
        }
        let ev1 = self.nx();
        self.line(format!(
            "  %\"{}\" = extractvalue {{i8*, i64}} %\"{}\", 0", ev1, iv2));
        let ev2 = self.nx();
        self.line(format!(
            "  %\"{}\" = extractvalue {{i8*, i64}} %\"{}\", 1", ev2, iv2));
        if view {
            // dead chain: pair -> str_view field stores (+ unused bitcast)
            let vn = self.uniq_label("str_view");
            self.reg_names.push(vn.clone());
            if IN_FN.with(|v| *v.borrow()) {
                FN_ALLOCAS.with(|f| f.borrow_mut()
                    .push((vn.clone(), "view".into())));
            } else {
                MAIN_ALLOCAS.with(|m| m.borrow_mut().push(vn.clone()));
            }
            for fld in [0u32, 1, 3] {
                let g = self.nx();
                self.line(format!(
                    "  %\"{}\" = getelementptr {{i64, i64, i8*, i64}}, {{i64, i64, i8*, i64}}* %\"{}\", i32 0, i32 {}",
                    g, vn, fld));
                self.silent();
                self.line(format!(
                    "  store i64 %\"{}\", i64* %\"{}\"", ev2, g));
            }
            let g2 = self.nx();
            self.line(format!(
                "  %\"{}\" = getelementptr {{i64, i64, i8*, i64}}, {{i64, i64, i8*, i64}}* %\"{}\", i32 0, i32 2",
                g2, vn));
            self.silent();
            self.line(format!(
                "  store i8* %\"{}\", i8** %\"{}\"", ev1, g2));
            let vbc = self.nx();
            self.line(format!(
                "  %\"{}\" = bitcast {{i64, i64, i8*, i64}}* %\"{}\" to i8*",
                vbc, vn));
            return format!("%\"{}\"", vbc);
        }
        let ch = self.nx();
        self.line(format!(
            "  %\"{}\" = call i8* @\"rawstr_char1\"(i8* %\"{}\", i64 %\"{}\")",
            ch, ev1, ev2));
        TEMP_STRS.with(|t| t.borrow_mut().push(format!("%\"{}\"", ch)));
        format!("%\"{}\"", ch)
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

// aug_assign: name targets (int checked / float unchecked) and
// subscript targets (unchecked read-modify-write on the raw data slot)
fn conv_aug_assign(b: &mut FnB, st: &Val, sc: &mut usize,
                   slot_ref: &dyn Fn(&str) -> String) {
    let op = st.get(2).str_of();
    let rhs_e = st.get(3);

    if st.get(1).head() == "attribute" {
        // self.pos op= v: field read, checked op, reload + store in ok
        let base = st.get(1).get(1);
        let fld = st.get(1).get(2).str_of();
        if base.head() != "name" { bail("attr aug base"); }
        let bn = base.get(1).str_of();
        let cls = fn_ty_of(&bn)
            .unwrap_or_else(|| bail("attr aug type"));
        let fields = class_fields(&cls)
            .unwrap_or_else(|| bail("class fields"));
        let (off, fty) = fields.iter().position(|(f, _)| f == &fld)
            .map(|i| ((i * 8) as i64, fields[i].1.clone()))
            .unwrap_or_else(|| bail("field"));
        let fs = F_SLOTS.with(|f| f.borrow().clone());
        let rhs = eval_expr(b, &rhs_e, slot_ref, slot_ref, sc, &fs);
        let lv = b.nx();
        b.line(format!("  %\"{}\" = load i8*, i8** %\"{}\"", lv, bn));
        let gp = b.nx();
        b.line(format!(
            "  %\"{}\" = getelementptr i8, i8* %\"{}\", i64 {}", gp, lv, off));
        let bc = b.nx();
        let lty = if fty == "float" { "double" } else { "i64" };
        let cast_ty = if fty == "float" { "double*" } else { "i64*" };
        b.line(format!(
            "  %\"{}\" = bitcast i8* %\"{}\" to {}", bc, gp, cast_ty));
        let ld = b.nx();
        b.line(format!(
            "  %\"{}\" = load {}, {}* %\"{}\"", ld, lty, lty, bc));
        if fty == "float" {
            let r = to_f64(b, rhs);
            let instr = match op.as_str() {
                "+=" => "fadd", "-=" => "fsub", "*=" => "fmul",
                _ => bail("attr aug float op"),
            };
            let res = b.nx();
            b.line(format!(
                "  %\"{}\" = {} double %\"{}\", {}", res, instr, ld, r));
            b.silent();
            b.line(format!(
                "  store double %\"{}\", double* %\"{}\"", res, bc));
        } else {
            let Typed::I64(r) = rhs else { bail("attr aug rhs") };
            let which = match op.as_str() {
                "+=" => "+", "-=" => "-", _ => bail("attr aug op"),
            };
            let res = b.checked_raw(&format!("%\"{}\"", ld), &r, which, sc);
            // panic_ok continuation: reload self + gep + bitcast + store
            let lv2 = b.nx();
            b.line(format!("  %\"{}\" = load i8*, i8** %\"{}\"",
                lv2, bn));
            let gp2 = b.nx();
            b.line(format!(
                "  %\"{}\" = getelementptr i8, i8* %\"{}\", i64 {}",
                gp2, lv2, off));
            let bc2 = b.nx();
            b.line(format!(
                "  %\"{}\" = bitcast i8* %\"{}\" to i64*", bc2, gp2));
            b.silent();
            b.line(format!(
                "  store i64 {}, i64* %\"{}\"", res, bc2));
        }
        return;
    }
    if st.get(1).head() == "subscript" {
        // l[k] op= v: rhs first, then obj/key, direct data gep (no checks)
        let base = st.get(1).get(1);
        if base.head() != "name" { bail("aug subscript base"); }
        let n = base.get(1).str_of();
        let elem = lst_elem_ty(&n);
        let fs = F_SLOTS.with(|f| f.borrow().clone());
        let rhs_v = eval_expr(b, &rhs_e, slot_ref, slot_ref, sc, &fs);
        let l = b.nx();
        b.line(format!("  %\"{}\" = load i8*, i8** {}", l, lst_slot(&n)));
        let k = b.expr_i64_raw(&st.get(1).get(2), slot_ref, sc);
        let bc = b.nx();
        b.line(format!(
            "  %\"{}\" = bitcast i8* %\"{}\" to {{i64, i64, i8*}}*", bc, l));
        let gd = b.nx();
        b.line(format!(
            "  %\"{}\" = getelementptr {{i64, i64, i8*}}, {{i64, i64, i8*}}* %\"{}\", i32 0, i32 2",
            gd, bc));
        let data = b.nx();
        b.line(format!("  %\"{}\" = load i8*, i8** %\"{}\"", data, gd));
        let dbc = b.nx();
        b.line(format!("  %\"{}\" = bitcast i8* %\"{}\" to i64*", dbc, data));
        let gep = b.nx();
        b.line(format!(
            "  %\"{}\" = getelementptr i64, i64* %\"{}\", i64 {}", gep, dbc, k));
        let ld = b.nx();
        b.line(format!("  %\"{}\" = load i64, i64* %\"{}\"", ld, gep));
        if elem == "float" {
            let cur = b.nx();
            b.line(format!(
                "  %\"{}\" = bitcast i64 %\"{}\" to double", cur, ld));
            let r = to_f64(b, rhs_v);
            let instr = match op.as_str() {
                "+=" => "fadd", "-=" => "fsub", "*=" => "fmul",
                _ => bail("aug float op"),
            };
            let res = b.nx();
            b.line(format!(
                "  %\"{}\" = {} double %\"{}\", {}", res, instr, cur, r));
            let ib = b.nx();
            b.line(format!(
                "  %\"{}\" = bitcast double %\"{}\" to i64", ib, res));
            b.silent();
            b.line(format!(
                "  store i64 %\"{}\", i64* %\"{}\"", ib, gep));
        } else {
            let Typed::I64(r) = rhs_v else { bail("aug int rhs") };
            let which = match op.as_str() {
                "+=" => "+", "-=" => "-", _ => bail("aug int op"),
            };
            let res = b.checked_raw(&format!("%\"{}\"", ld), &r, which, sc);
            b.silent();
            b.line(format!(
                "  store i64 {}, i64* %\"{}\"", res, gep));
        }
        return;
    }

    let slot = st.get(1).get(1).str_of();
    let fs = F_SLOTS.with(|f| f.borrow().clone());
    if is_local_f(&slot) || fs.iter().any(|f| f == &slot) {
        // float aug: rhs, load target, unchecked fop, store
        let rhs_v = eval_mod(b, &rhs_e, &fs, sc);
        let r = to_f64(b, rhs_v);
        let tgt = if is_local_f(&slot) { format!("%\"{}\"", slot) }
                  else { format!("@\"{}\"", slot) };
        let l = b.nx();
        b.line(format!("  %\"{}\" = load double, double* {}", l, tgt));
        let instr = match op.as_str() {
            "+=" => "fadd", "-=" => "fsub", "*=" => "fmul",
            _ => bail("aug float op"),
        };
        let res = b.nx();
        b.line(format!(
            "  %\"{}\" = {} double %\"{}\", {}", res, instr, l, r));
        b.silent();
        b.line(format!("  store double %\"{}\", double* {}", res, tgt));
        return;
    }
    let rhs = b.expr_i64_raw(&rhs_e, slot_ref, sc);
    let which = match op.as_str() {
        "+=" => "+", "-=" => "-", _ => bail("aug op"),
    };
    let target = if is_local_i(&slot) { format!("%\"{}\"", slot) }
                 else { slot_ref(&slot) };
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
    static MAIN_ALLOCAS: RefCell<Vec<String>> = RefCell::new(Vec::new());
    static FN_B: RefCell<Vec<String>> = RefCell::new(Vec::new()); // local bools
    static FN_STOR: RefCell<Vec<(String, String)>> = RefCell::new(Vec::new());
    static FN_PARAM_NAMES: RefCell<Vec<String>> = RefCell::new(Vec::new());
    static CV_ERR_NAME: RefCell<Option<String>> = RefCell::new(None);
    static TEMP_STRS: RefCell<Vec<String>> = RefCell::new(Vec::new());
    static COMPARE_VIEW: RefCell<bool> = RefCell::new(false);
    static SPLIT_FORM: RefCell<bool> = RefCell::new(false);
    static PENDING_PAIR: RefCell<Option<String>> = RefCell::new(None);
    static SLICE_NO_COPY: RefCell<bool> = RefCell::new(false);
    static DYN_CLASSES: RefCell<Vec<String>> = RefCell::new(Vec::new());
    static PY_SLOTS: RefCell<Vec<String>> = RefCell::new(Vec::new());
    // enclosing match_end targets: while_end branches back to the match
    // merge, an inner match ends with a forward branch to the parent's
    // merge (jsonparse main evidence)
    static MATCH_END: RefCell<Vec<String>> = RefCell::new(Vec::new());
    // whether the tagged-union Json runtime is pulled in
    static TAGGED: RefCell<bool> = RefCell::new(false);
    // loop-body nesting depth; a match case body records the depth it
    // entered at so the block-fallthrough rule can tell a case body
    // (branch to match_end) from a while body (the loop re-branches)
    static LOOP_DEPTH: RefCell<usize> = RefCell::new(0);
    static CASE_DEPTH: RefCell<Vec<usize>> = RefCell::new(Vec::new());
    static PY_RETS: RefCell<Vec<String>> = RefCell::new(Vec::new());
    // dynamic-instance layer: enums, classes, method signatures
    static ENUMS: RefCell<Vec<(String, Vec<String>)>> = RefCell::new(Vec::new());
    static CLASSES: RefCell<Vec<(String, Vec<(String, String)>)>> =
        RefCell::new(Vec::new()); // (class, [(field, ty)])
    static FN_TY: RefCell<Vec<(String, String)>> = RefCell::new(Vec::new());
    static FN_S: RefCell<Vec<String>> = RefCell::new(Vec::new()); // local strs
}

fn is_declared(name: &str) -> bool {
    TAIL.with(|t| t.borrow().iter()
        .any(|g| g.contains(&format!("@\"{}\"", name))))
}

// int/float comparison condition -> i1 ref; ops shared by while/if
// i1-producing expressions: comparisons, str ==, is, isdigit,
// bool names, and/or sc chains (truthy ending for conditions,
// unbox ending for bool assignments)
fn eval_i1(b: &mut FnB, e: &Val, sc: &mut usize) -> String {
    let fs = F_SLOTS.with(|f| f.borrow().clone());
    match e.head() {
        "and" | "or" => emit_sc(b, e, sc, true),
        "is" => {
            let v = eval_mod(b, &e.get(1), &fs, sc);
            let r = match v {
                Typed::Inst(r) | Typed::Str(r) => r,
                _ => bail("is operand"),
            };
            let ic = b.nx();
            b.line(format!(
                "  %\"{}\" = icmp eq i8* {}, null", ic, r));
            format!("%\"{}\"", ic)
        }
        "call" if e.get(1).head() == "attribute"
            && e.get(1).get(2).str_of() == "isdigit" => {
            let base = e.get(1).get(1);
            let v = eval_mod(b, &base, &fs, sc);
            let r = to_raw(b, v, sc);
            let c = b.nx();
            b.line(format!(
                "  %\"{}\" = call i1 @\"rawstr_isdigit\"(i8* {})", c, r));
            format!("%\"{}\"", c)
        }
        "==" | "!=" | "<" | "<=" | ">" | ">=" => {
            // compare-context subscripts: dead value conversion (view
            // mode) first, then the fused compare with fresh loads
            let fused_pattern = e.get(1).head() == "subscript"
                && e.get(1).get(1).head() == "name"
                && e.get(2).head() == "const"
                && matches!(e.get(2).get(1), Val::Str(_)) && {
                let bn = e.get(1).get(1).get(1).str_of();
                STR_SLOTS.with(|t| t.borrow().iter().any(|f| f == &bn))
                    || is_local_s(&bn)
            };
            if fused_pattern {
                // dead value conversion pauses after insertvalue; the
                // rhs const chain (gep+create_str) lands between the
                // pair halves, then the view stores complete it
                PENDING_PAIR.with(|c| *c.borrow_mut() =
                    Some(String::new()));
                COMPARE_VIEW.with(|c| *c.borrow_mut() = true);
            }
            let lt = eval_mod(b, &e.get(1), &fs, sc);
            COMPARE_VIEW.with(|c| *c.borrow_mut() = false);
            let rt = eval_mod(b, &e.get(2), &fs, sc);
            let pending = PENDING_PAIR.with(|c| c.borrow().clone());
            PENDING_PAIR.with(|c| *c.borrow_mut() = None);
            if let Some(pr) = pending {
                if !pr.is_empty() { b.finish_view_split(&pr); }
            }
            // fused subscript-vs-const: s[k] op "c" (no char1/cv)
            if matches!(lt, Typed::Str(_))
                && e.get(1).head() == "subscript"
                && e.get(2).head() == "const"
                && matches!(e.get(2).get(1), Val::Str(_))
                && matches!(rt, Typed::PStr(_)) {
                let _old = match lt { Typed::Str(r) => r, _ => unreachable!() };
                // fresh base load AFTER the dead chain (ref: load s)
                let bn = e.get(1).get(1).get(1).str_of();
                let bslot = if is_local_s(&bn) {
                    format!("%\"{}\"", bn) } else { format!("@\"{}\"", bn) };
                let sl = b.nx();
                b.line(format!("  %\"{}\" = load i8*, i8** {}",
                    sl, bslot));
                let sr = format!("%\"{}\"", sl);
                let idxe = e.get(1).get(2);
                let iv = eval_mod(b, &idxe, &fs, sc);
                let Typed::I64(k) = iv else { bail("fused idx") };
                let text = e.get(2).get(1).str_of();
                let blen = text.chars().count() as i64;
                let gname = add_str(sc, &text);
                let g = b.nx();
                b.line(format!(
                    "  %\"{}\" = getelementptr [{} x i8], [{} x i8]* @\"{}\", i32 0, i32 0",
                    g, blen + 1, blen + 1, gname));
                match e.head() {
                    "==" | "!=" => {
                        let c = b.nx();
                        b.line(format!(
                            "  %\"{}\" = call i1 @\"rawstr_at_eq_cstr\"(i8* {}, i64 {}, i8* %\"{}\", i64 {})",
                            c, sr, k, g, blen));
                        if e.head() == "!=" {
                            let x = b.nx();
                            b.line(format!(
                                "  %\"{}\" = xor i1 %\"{}\", -1", x, c));
                            return format!("%\"{}\"", x);
                        }
                        return format!("%\"{}\"", c);
                    }
                    _ => {
                        let c = b.nx();
                        b.line(format!(
                            "  %\"{}\" = call i64 @\"rawstr_at_cmp_cstr\"(i8* {}, i64 {}, i8* %\"{}\", i64 {})",
                            c, sr, k, g, blen));
                        let pred = match e.head() {
                            ">=" => "sge", "<=" => "sle",
                            ">" => "sgt", _ => "slt" };
                        let ic = b.nx();
                        b.line(format!(
                            "  %\"{}\" = icmp {} i64 %\"{}\", 0", ic, pred, c));
                        return format!("%\"{}\"", ic);
                    }
                }
            }
            if e.head() == "==" && (matches!(lt, Typed::Str(_) | Typed::PStr(_))
                || matches!(rt, Typed::Str(_) | Typed::PStr(_))) {
                // str ==: const rhs gets a FRESH constant slot + gep
                let lr = to_raw(b, lt, sc);
                let (rr, rlen) = if e.get(2).head() == "const"
                    && matches!(e.get(2).get(1), Val::Str(_)) {
                    let text = e.get(2).get(1).str_of();
                    let gname = add_str(sc, &text);
                    let blen = text.chars().count() as i64;
                    let g = b.nx();
                    b.line(format!(
                        "  %\"{}\" = getelementptr [{} x i8], [{} x i8]* @\"{}\", i32 0, i32 0",
                        g, blen + 1, blen + 1, gname));
                    (format!("%\"{}\"", g), blen)
                } else {
                    (to_raw(b, rt, sc), 0i64)
                };
                let c = b.nx();
                b.line(format!(
                    "  %\"{}\" = call i1 @\"rawstr_eq_cstr\"(i8* {}, i8* {}, i64 {})",
                    c, lr, rr, rlen));
                return format!("%\"{}\"", c);
            }
            let pred = match e.head() {
                "<" => "slt", "<=" => "sle", ">" => "sgt", ">=" => "sge",
                "==" => "eq", _ => "ne",
            };
            if matches!(lt, Typed::F64(_)) || matches!(rt, Typed::F64(_)) {
                // mixed: silent, sitofp, then the fcmp slot (calc)
                let l = to_f64(b, lt);
                let r = to_f64(b, rt);
                let ic = b.nx();
                let fp = match pred { "slt" => "olt", "sle" => "ole",
                                     "sgt" => "ogt", "sge" => "oge",
                                     "eq" => "oeq", _ => "one" };
                b.line(format!(
                    "  %\"{}\" = fcmp {} double {}, {}", ic, fp, l, r));
                format!("%\"{}\"", ic)
            } else {
                let (Typed::I64(l), Typed::I64(r)) = (lt, rt) else {
                    bail("cond types") };
                let ic = b.nx();
                b.line(format!(
                    "  %\"{}\" = icmp {} i64 {}, {}", ic, pred, l, r));
                format!("%\"{}\"", ic)
            }
        }
        "const" if matches!(e.get(1), Val::Bool(_)) => {
            matches!(&e.items()[1], Val::Bool(v) if *v).to_string()
        }
        "name" if is_local_b(&e.get(1).str_of()) => {
            let l = b.nx();
            b.line(format!(
                "  %\"{}\" = load i1, i1* %\"{}\"", l, e.get(1).str_of()));
            format!("%\"{}\"", l)
        }
        _ => bail("i1 expr"),
    }
}

// and/or short-circuit: boxed sc_result chain; the sc_end block is
// created before the first operand's eval blocks, then per-operand
// sc_finish/sc_next, truthy_call, truthy_merge (calc, parse_number).
// The IR and/or is variadic: operand k+1 evaluates inside sc_next.k
fn emit_sc(b: &mut FnB, e: &Val, sc: &mut usize, truthy: bool) -> String {
    let is_and = e.head() == "and";
    let srn = b.uniq_label("sc_result");
    b.reg_names.push(srn.clone());
    b.line(format!("  %\"{}\" = alloca {{i32, i8*}}*", srn));
    let ed_lbl = b.uniq_label("sc_end");
    let ed_b = b.add_block(&ed_lbl);
    let n_ops = e.items().len() - 1;
    let mut cur = eval_i1(b, &e.get(1), sc);
    for k in 1..n_ops {
        let f_lbl = b.uniq_label("sc_finish");
        let n_lbl = b.uniq_label("sc_next");
        b.silent();
        if is_and {
            b.line(format!(
                "  br i1 {}, label %\"{}\", label %\"{}\"", cur, n_lbl, f_lbl));
        } else {
            b.line(format!(
                "  br i1 {}, label %\"{}\", label %\"{}\"", cur, f_lbl, n_lbl));
        }
        let fb = b.add_block(&f_lbl);
        let nb = b.add_block(&n_lbl);
        b.pos(fb);
        let cb = b.nx();
        b.line(format!(
            "  %\"{}\" = call {{i32, i8*}}* @\"create_bool\"(i1 {})", cb, cur));
        b.silent();
        b.line(format!(
            "  store {{i32, i8*}}* %\"{}\", {{i32, i8*}}** %\"{}\"", cb, srn));
        b.silent();
        b.line(format!("  br label %\"{}\"", ed_lbl));
        b.pos(nb);
        cur = eval_i1(b, &e.get(k + 1), sc);
    }
    if !truthy {
        // assignment and/or: free TEMP strs produced by B's eval
        let temps = TEMP_STRS.with(|t| t.borrow().clone());
        for tr in temps.iter() {
            b.silent();
            b.line(format!("  call void @\"rawstr_free\"(i8* {})", tr));
        }
        TEMP_STRS.with(|t| *t.borrow_mut() = Vec::new());
    }
    let cb2 = b.nx();
    b.line(format!(
        "  %\"{}\" = call {{i32, i8*}}* @\"create_bool\"(i1 {})", cb2, cur));
    b.silent();
    b.line(format!(
        "  store {{i32, i8*}}* %\"{}\", {{i32, i8*}}** %\"{}\"", cb2, srn));
    b.silent();
    b.line(format!("  br label %\"{}\"", ed_lbl));
    b.pos(ed_b);
    let ld = b.nx();
    b.line(format!(
        "  %\"{}\" = load {{i32, i8*}}*, {{i32, i8*}}** %\"{}\"", ld, srn));
    if !truthy {
        let ub = b.nx();
        b.line(format!(
            "  %\"{}\" = call i1 @\"unbox_bool\"({{i32, i8*}}* %\"{}\")",
            ub, ld));
        return format!("%\"{}\"", ub);
    }
    let nz = b.nx();
    b.line(format!(
        "  %\"{}\" = icmp eq {{i32, i8*}}* %\"{}\", null", nz, ld));
    let tm_lbl = b.uniq_label("truthy_merge");
    let tc_lbl = b.uniq_label("truthy_call");
    b.silent();
    b.line(format!(
        "  br i1 %\"{}\", label %\"{}\", label %\"{}\"", nz, tm_lbl, tc_lbl));
    let tcb = b.add_block(&tc_lbl);
    let tmb = b.add_block(&tm_lbl);
    b.pos(tcb);
    let tv = b.nx();
    b.line(format!(
        "  %\"{}\" = call i1 @\"pyobj_truthy\"({{i32, i8*}}* %\"{}\")",
        tv, ld));
    b.silent();
    b.line(format!("  br label %\"{}\"", tm_lbl));
    b.pos(tmb);
    let ph = b.nx();
    b.line(format!(
        "  %\"{}\" = phi  i1 [0, %\"{}\"], [%\"{}\", %\"{}\"]",
        ph, ed_lbl, tv, tc_lbl));
    format!("%\"{}\"", ph)
}

// conditions share eval_i1 (comparisons, sc chains, bools)
fn emit_cond(b: &mut FnB, cond: &Val, sc: &mut usize) -> String {
    eval_i1(b, cond, sc)
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
    let (fill_int, fill_flt) = match fill.items().get(1) {
        Some(Val::List(vs)) if vs.len() == 1 => match &vs[0] {
            Val::List(el) if el.len() == 2 && el[0] == Val::Str("const".into())
                && matches!(el[1], Val::Int(_)) =>
                (Some(el[1].int_of()), None),
            Val::List(el) if el.len() == 2 && el[0] == Val::Str("const".into())
                && matches!(el[1], Val::Float(_)) =>
                (None, Some(match el[1] { Val::Float(v) => v, _ => 0.0 })),
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
    if let Some(iv) = fill_int {
        let lp = b.nx();
        b.line(format!("  %\"{}\" = load i8*, i8** %\"{}\"", lp, fln));
        let pu = b.nx();
        b.line(format!(
            "  %\"{}\" = call i64 @\"rawlist_push\"(i8* %\"{}\", i64 {})",
            pu, lp, iv));
    } else {
        // float fill: const bitcast, list load, then the push slot
        let fv = fill_flt.unwrap_or(0.0);
        let ib = b.nx();
        b.line(format!(
            "  %\"{}\" = bitcast double {} to i64", ib, double_bits(fv)));
        let lp = b.nx();
        b.line(format!("  %\"{}\" = load i8*, i8** %\"{}\"", lp, fln));
        let pu = b.nx();
        b.line(format!(
            "  %\"{}\" = call i64 @\"rawlist_push\"(i8* %\"{}\", i64 %\"{}\")",
            pu, lp, ib));
    }
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
    if IN_FN.with(|v| *v.borrow()) && st.get(3).head() == "subscript"
        && st.get(3).get(1).get(1).str_of() == "list" {
        // function-local list: alloca + rawlist_new + store
        let elem0 = st.get(3).get(2).get(1).str_of();
        let elem = if elem0 == "Json" { "json".to_string() } else { elem0 };
        if !is_class(&elem) && elem != "int" && elem != "str"
            && elem != "float" && elem != "json" { bail("local list elem"); }
        FN_ALLOCAS.with(|f| f.borrow_mut().push((name.clone(), "list".into())));
        FN_L.with(|l| l.borrow_mut().push((name.clone(), elem)));
        let c = b.nx();
        b.line(format!("  %\"{}\" = call i8* @\"rawlist_new\"(i64 8)", c));
        b.silent();
        b.line(format!("  store i8* %\"{}\", i8** %\"{}\"", c, name));
        return;
    }
    if IN_FN.with(|v| *v.borrow()) && st.get(3).head() == "subscript"
        && st.get(3).get(1).get(1).str_of() == "dict" {
        // function-local dict[str,Json]: alloca + rawdict_new + store
        // (jsonparse_json parse_object o evidence)
        let tp = st.get(3).get(2);
        let tv = tp.items().get(1).cloned().unwrap_or(Val::Null);
        let vty = tv_valtype(&tv);
        FN_ALLOCAS.with(|f| f.borrow_mut().push((name.clone(), "list".into())));
        DCT_SLOTS.with(|t| t.borrow_mut().push(name.clone()));
        DCT_KEYS.with(|m| m.borrow_mut().push((name.clone(), vty)));
        let va = match &tv { Val::List(vs) if vs.len() == 2 =>
            vs[1].get(1).str_of(), _ => String::new() };
        DCT_VALS.with(|m| m.borrow_mut().push((name.clone(), va)));
        FN_D.with(|f| f.borrow_mut().push(name.clone()));
        let c = b.nx();
        b.line(format!("  %\"{}\" = call i8* @\"rawdict_new\"()", c));
        b.silent();
        b.line(format!("  store i8* %\"{}\", i8** %\"{}\"", c, name));
        return;
    }
    if IN_FN.with(|v| *v.borrow()) && st.get(3).head() == "name" {
        // function-local binding: record the alloca, typed init store
        let t = st.get(3).get(1).str_of();
        if t == "str" {
            // str local: alloca (null in splice), free-old + store
            FN_ALLOCAS.with(|f| f.borrow_mut().push((name.clone(), "str".into())));
            FN_S.with(|y| y.borrow_mut().push(name.clone()));
            let fs = F_SLOTS.with(|f| f.borrow().clone());
            SLICE_NO_COPY.with(|c| *c.borrow_mut() = true);
            let v = eval_mod(b, &init, &fs, sc);
            SLICE_NO_COPY.with(|c| *c.borrow_mut() = false);
            let r = to_raw(b, v, sc);
            b.silent(); // value conversion slot (calc: .4 -> .6)
            TEMP_STRS.with(|t| t.borrow_mut().retain(|x| x != &r));
            let oldr = b.nx();
            b.line(format!(
                "  %\"{}\" = load i8*, i8** %\"{}\"", oldr, name));
            b.silent();
            b.line(format!(
                "  call void @\"rawstr_free\"(i8* %\"{}\")", oldr));
            b.silent();
            b.line(format!("  store i8* {}, i8** %\"{}\"", r, name));
            return;
        }
        if t == "bool" {
            if is_local_b(&name) { bail("dup bool local"); }
            FN_ALLOCAS.with(|f| f.borrow_mut().push((name.clone(), "bool".into())));
            FN_B.with(|y| y.borrow_mut().push(name.clone()));
            b.silent();
            let v = matches!(&init.items()[1], Val::Bool(v) if *v);
            b.line(format!("  store i1 {}, i1* %\"{}\"", v, name));
            return;
        }
        if t != "int" && t != "float" {
            if is_class(&t) {
                // instance local: storage typed by the init expr
                if fn_ty_of(&name).is_some() { bail("dup inst local"); }
                let fs = F_SLOTS.with(|f| f.borrow().clone());
                let v = eval_mod(b, &init, &fs, sc);
                match v {
                    Typed::Inst(r) => {
                        FN_ALLOCAS.with(|f| f.borrow_mut()
                            .push((name.clone(), "i8*".into())));
                        FN_TY.with(|y| y.borrow_mut()
                            .push((name.clone(), t.clone())));
                        FN_STOR.with(|y| y.borrow_mut()
                            .push((name.clone(), "i8*".into())));
                        b.silent();
                        b.line(format!(
                            "  store i8* {}, i8** %\"{}\"", r, name));
                    }
                    Typed::I64(r) => {
                        FN_ALLOCAS.with(|f| f.borrow_mut()
                            .push((name.clone(), "i64".into())));
                        FN_TY.with(|y| y.borrow_mut()
                            .push((name.clone(), t.clone())));
                        FN_STOR.with(|y| y.borrow_mut()
                            .push((name.clone(), "i64".into())));
                        b.silent();
                        b.line(format!(
                            "  store i64 {}, i64* %\"{}\"", r, name));
                    }
                    _ => bail("inst local init"),
                }
                return;
            }
            bail("local type");
        }
        if is_local_i(&name) || is_local_f(&name) { bail("dup local"); }
        FN_ALLOCAS.with(|f| f.borrow_mut().push((name.clone(), t.to_string())));
        let fs = F_SLOTS.with(|f| f.borrow().clone());
        let v = eval_mod(b, &init, &fs, sc);
        if t == "float" {
            let r = to_f64(b, v);
            b.silent();
            b.line(format!("  store double {}, double* %\"{}\"", r, name));
            FN_F.with(|f| f.borrow_mut().push(name.clone()));
        } else {
            let Typed::I64(r) = v else { bail("local init type") };
            b.silent();
            b.line(format!("  store i64 {}, i64* %\"{}\"", r, name));
            FN_I.with(|f| f.borrow_mut().push(name.clone()));
        }
        return;
    }
    if st.get(3).head() == "subscript"
        && st.get(3).get(1).get(1).str_of() == "dict" {
        let tp = st.get(3).get(2);
        let tv = tp.items().get(1).cloned().unwrap_or(Val::Null);
        let ok_types = tp.head() == "tuple"
            && matches!(&tv, Val::List(vs) if vs.len() == 2
                && vs.iter().all(|v| ["int", "str", "Json"].contains(&v.get(1).str_of().as_str())));
        if !ok_types { bail("dict elem types"); }
        let vty = tv_valtype(&tv);
        // dict[str,Json]: the VALUE annotation (second tuple member)
        let val_ann = match &tv { Val::List(vs) if vs.len() == 2 =>
            vs[1].get(1).str_of(), _ => String::new() };
        if init.head() == "call" && val_ann == "Json" {
            // dict[str,Json] = json_dict(x): unwrap the tagged dict pointer
            // into the raw dict global (jsonparse_json main o)
            *sc += 1;
            DCT_SLOTS.with(|t| t.borrow_mut().push(name.clone()));
            DCT_KEYS.with(|m| m.borrow_mut().push((name.clone(), vty)));
            DCT_VALS.with(|m| m.borrow_mut().push((name.clone(), val_ann.clone())));
            let fs = F_SLOTS.with(|f| f.borrow().clone());
            let v = eval_mod(b, &init, &fs, sc);
            let r = match v {
                Typed::Inst(r) | Typed::Str(r) => r,
                _ => bail("json_dict init"),
            };
            b.silent();
            b.line(format!("  store i8* {}, i8** @\"{}\"", r, name));
            tail_push(format!("@\"{}\" = global i8* null", name));
            return;
        }
        if init.head() != "dict"
            || !matches!(init.items().get(1), Some(Val::List(v)) if v.is_empty()) {
            bail("dict init");
        }
        *sc += 1; // module binding consumes a slot
        DCT_SLOTS.with(|t| t.borrow_mut().push(name.clone()));
        DCT_KEYS.with(|m| m.borrow_mut().push(
            (name.clone(), tv_valtype(&tv))));
        let va2 = match &tv { Val::List(vs) if vs.len() == 2 =>
            vs[1].get(1).str_of(), _ => String::new() };
        DCT_VALS.with(|m| m.borrow_mut().push((name.clone(), va2)));
        let c = b.nx();
        b.line(format!("  %\"{}\" = call i8* @\"rawdict_new\"()", c));
        b.silent();
        b.line(format!("  store i8* %\"{}\", i8** @\"{}\"", c, name));
        tail_push(format!("@\"{}\" = global i8* null", name));
    } else if st.get(3).head() == "subscript"
        && st.get(3).get(1).get(1).str_of() == "list" {
        let elem0 = st.get(3).get(2).get(1).str_of();
        let elem = if elem0 == "Json" { "json".to_string() } else { elem0 };
        if elem != "int" && elem != "float" && elem != "str" && elem != "json"
            && !is_class(&elem) && !is_enum(&elem) {
            bail("list elem type");
        }
        *sc += 1; // module binding consumes a slot
        LST_SLOTS.with(|t| t.borrow_mut().push(name.clone()));
        LST_ELEM.with(|m| m.borrow_mut().push((name.clone(), elem.clone())));
        if init.head() == "list" {
            // [] literal, [v] * n fill loop, or non-empty literal
            let elems = init.items().get(1).cloned().unwrap_or(Val::Null);
            if matches!(&elems, Val::List(v) if v.is_empty()) {
                let c = b.nx();
                b.line(format!("  %\"{}\" = call i8* @\"rawlist_new\"(i64 8)", c));
                b.silent();
                b.line(format!("  store i8* %\"{}\", i8** @\"{}\"", c, name));
            } else if let Val::List(vs) = &elems {
                // non-empty literal: new + per-element eval + push
                let c = b.nx();
                b.line(format!("  %\"{}\" = call i8* @\"rawlist_new\"(i64 8)", c));
                let fs = F_SLOTS.with(|f| f.borrow().clone());
                for el in vs.iter() {
                    let v = eval_mod(b, el, &fs, sc);
                    if elem == "float" {
                        let r = to_f64(b, v);
                        let ib = b.nx();
                        b.line(format!(
                            "  %\"{}\" = bitcast double {} to i64", ib, r));
                        let pu = b.nx();
                        b.line(format!(
                            "  %\"{}\" = call i64 @\"rawlist_push\"(i8* %\"{}\", i64 %\"{}\")",
                            pu, c, ib));
                    } else {
                        let Typed::I64(r) = v else { bail("elem type") };
                        let pu = b.nx();
                        b.line(format!(
                            "  %\"{}\" = call i64 @\"rawlist_push\"(i8* %\"{}\", i64 {})",
                            pu, c, r));
                    }
                }
                b.silent();
                b.line(format!("  store i8* %\"{}\", i8** @\"{}\"", c, name));
            } else { bail("list init"); }
        } else if init.head() == "*" {
            emit_fill(b, &name, &init.get(1), &init.get(2), sc);
        } else if elem == "json" && init.head() == "call" {
            // list[Json] = json_list(x): unwrap the tagged list pointer
            // into the raw list global (jsonparse_json main items)
            let fs = F_SLOTS.with(|f| f.borrow().clone());
            let v = eval_mod(b, &init, &fs, sc);
            let r = match v {
                Typed::Inst(r) | Typed::Str(r) => r,
                _ => bail("json_list init"),
            };
            b.silent();
            b.line(format!("  store i8* {}, i8** @\"{}\"", r, name));
        } else { bail("list init"); }
        tail_push(format!("@\"{}\" = global i8* null", name));
    } else {
        let anno = st.get(3).get(1).str_of();
        if anno == "Json" {
            // Json module binding: i8* global holding the tagged block
            // pointer (jsonparse_json main data evidence)
            JSON_SLOTS.with(|sl| sl.borrow_mut().push(name.clone()));
            *sc += 1;
            tail_push(format!("@\"{}\" = global i8* null", name));
            let fs = F_SLOTS.with(|f| f.borrow().clone());
            let v = eval_mod(b, &init, &fs, sc);
            let r = match v {
                Typed::Inst(r) | Typed::Str(r) => r,
                _ => bail("json init"),
            };
            b.silent();
            b.line(format!("  store i8* {}, i8** @\"{}\"", r, name));
            return;
        }
        if anno == "str" {
            STR_SLOTS.with(|sl| sl.borrow_mut().push(name.clone()));
            if !matches!(&init.items().get(1), Some(Val::Str(_))) {
                // call/expr init: no init constant (doc = input());
                // slice inits keep the slice's own buffer (no copy)
                SLICE_NO_COPY.with(|c| *c.borrow_mut() = true);
                *sc += 1;
                tail_push(format!("@\"{}\" = global i8* null", name));
                let fsx = F_SLOTS.with(|f| f.borrow().clone());
                let v = eval_mod(b, &init, &fsx, sc);
                let r = to_raw(b, v, sc);
                let oldr = b.nx();
                b.line(format!(
                    "  %\"{}\" = load i8*, i8** @\"{}\"", oldr, name));
                b.silent();
                b.line(format!(
                    "  call void @\"rawstr_free\"(i8* %\"{}\")", oldr));
                b.silent();
                b.line(format!(
                    "  store i8* {}, i8** @\"{}\"", r, name));
                return;
            }
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
            F_SLOTS.with(|f| f.borrow_mut().push(name.clone()));
            let const_f = match &init.items()[1] {
                Val::Float(v) => Some(*v), _ => None };
            if let Some(f) = const_f {
                *sc += 1;
                tail_push(format!("@\"{}\" = global double {}",
                                  name, double_bits(f)));
                b.silent();
                b.line(format!("  store double {}, double* @\"{}\"",
                               double_bits(f), name));
            } else {
                // expression init: eval FIRST, then slot + store
                let fs = F_SLOTS.with(|f| f.borrow().clone());
                let v = eval_mod(b, &init, &fs, sc);
                let r = to_f64(b, v);
                *sc += 1;
                tail_push(format!("@\"{}\" = global double {}",
                                  name, double_bits(0.0)));
                b.silent();
                b.line(format!("  store double {}, double* @\"{}\"",
                               r, name));
            }
        } else {
            // int binding: rhs eval first, then slot + global + store
            // (spectral: rhs-created strings number before the slot)
            if init.head() == "const" && matches!(init.get(1), Val::Int(_)) {
                *sc += 1;
                tail_push(format!("@\"{}\" = global i64 0", name));
                b.silent();
                b.line(format!("  store i64 {}, i64* @\"{}\"",
                               init.get(1).int_of(), name));
            } else if init.head() == "name" {
                let src = init.get(1).str_of();
                let l = b.nx();
                b.line(format!("  %\"{}\" = load i64, i64* @\"{}\"", l, src));
                *sc += 1;
                tail_push(format!("@\"{}\" = global i64 0", name));
                b.silent();
                b.line(format!("  store i64 %\"{}\", i64* @\"{}\"", l, name));
            } else {
                let fs = F_SLOTS.with(|f| f.borrow().clone());
                let v = eval_mod(b, &init, &fs, sc);
                let Typed::I64(r) = v else { bail("ann_assign type") };
                *sc += 1;
                tail_push(format!("@\"{}\" = global i64 0", name));
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
    if IN_FN.with(|v| *v.borrow()) && (is_local_i(&name) || is_local_f(&name)) {
        let fs = F_SLOTS.with(|f| f.borrow().clone());
        let v = eval_mod(b, &rhs, &fs, sc);
        if is_local_f(&name) {
            let r = to_f64(b, v);
            b.silent();
            b.line(format!("  store double {}, double* %\"{}\"", r, name));
        } else {
            let Typed::I64(r) = v else { bail("local assign type") };
            b.silent();
            b.line(format!("  store i64 {}, i64* %\"{}\"", r, name));
        }
        return;
    }
    let is_f = F_SLOTS.with(|f| f.borrow().iter().any(|x| x == &name));
    let is_s = STR_SLOTS.with(|s| s.borrow().iter().any(|x| x == &name));
    if is_f {
        let fs = F_SLOTS.with(|f| f.borrow().clone());
        let v = eval_mod(b, &rhs, &fs, sc);
        let r = to_f64(b, v);
        b.silent();
        b.line(format!("  store double {}, double* @\"{}\"", r, name));
    } else if is_local_b(&name) {
        // bool local: const True/False direct, and/or via sc+unbox
        if rhs.head() == "const" && matches!(rhs.get(1), Val::Bool(_)) {
            let v = matches!(&rhs.items()[1], Val::Bool(v) if *v);
            b.silent();
            b.line(format!("  store i1 {}, i1* %\"{}\"", v, name));
        } else {
            unsafe { SC_PTR = sc; }
            let rhs2 = st.get(2);
            let r = if rhs2.head() == "and" || rhs2.head() == "or" {
                emit_sc(b, &rhs2, sc, false) // assignment: unbox_bool
            } else { eval_i1(b, &rhs2, sc) };
            b.silent();
            b.line(format!("  store i1 {}, i1* %\"{}\"", r, name));
        }
    } else if fn_ty_of(&name).is_some() {
        // instance local store by storage type
        let fs = F_SLOTS.with(|f| f.borrow().clone());
        let v = eval_mod(b, &rhs, &fs, sc);
        let stor = inst_stor(&name).unwrap_or_else(|| "i64".into());
        match (v, stor.as_str()) {
            (Typed::Inst(r), "i8*") => {
                b.silent();
                b.line(format!("  store i8* {}, i8** %\"{}\"", r, name));
            }
            (Typed::Inst(r), _) => {
                let pt = b.nx();
                b.line(format!(
                    "  %\"{}\" = ptrtoint i8* {} to i64", pt, r));
                b.silent();
                b.line(format!("  store i64 %\"{}\", i64* %\"{}\"", pt, name));
            }
            (Typed::I64(r), _) => {
                b.silent();
                b.line(format!("  store i64 {}, i64* %\"{}\"", r, name));
            }
            _ => bail("inst assign type"),
        }
    } else if !is_s && !is_local_s(&name)
        && !is_declared(&name) && !is_local_i(&name)
        && !is_local_f(&name) && !is_local_b(&name)
        && fn_ty_of(&name).is_none() {
        // Json subscript read: it = items[i] (list[Json]) or n1 = o["id"]
        // (dict[str,Json]). The element is an i64 slot bit-pattern; the
        // target auto-declares a Json global and inttoptr's the bits
        // (jsonparse_json main evidence)
        if rhs.head() == "subscript" && rhs.get(1).head() == "name" {
            let bn = rhs.get(1).get(1).str_of();
            let is_json_elem =
                (LST_SLOTS.with(|t| t.borrow().iter().any(|f| f == &bn))
                    && lst_elem_ty(&bn) == "json")
                || (FN_L.with(|t| t.borrow().iter().any(|(k, e)|
                        k == &bn && e == "json")))
                || (DCT_SLOTS.with(|t| t.borrow().iter().any(|f| f == &bn))
                    && dct_key_ty(&bn) == "str" && dct_val_is_json(&bn));
            if is_json_elem {
                // rhs (with its bounds-check panic string) is created
                // BEFORE the target binding, matching _convert_node ->
                // _declare_var order in the reference
                let fs = F_SLOTS.with(|f| f.borrow().clone());
                let v = eval_mod(b, &rhs, &fs, sc);
                let Typed::I64(bits) = v else { bail("json subscript") };
                JSON_SLOTS.with(|sl| sl.borrow_mut().push(name.clone()));
                *sc += 1;
                tail_push(format!("@\"{}\" = global i8* null", name));
                let pt = b.nx();
                b.line(format!(
                    "  %\"{}\" = inttoptr i64 {} to i8*", pt, bits));
                b.silent();
                b.line(format!("  store i8* %\"{}\", i8** @\"{}\"", pt, name));
                return;
            }
        }
        // untyped container literals: dynamic pyobj (parse_array/object)
        if rhs.head() == "list" || rhs.head() == "dict" {
            let elems = rhs.items().get(1).cloned().unwrap_or(Val::Null);
            let empty = matches!(&elems, Val::List(v) if v.is_empty());
            if empty {
                let ctor = if rhs.head() == "list" { "create_list" }
                           else { "create_dict" };
                let c = b.nx();
                b.line(format!(
                    "  %\"{}\" = call {{i32, i8*}}* @\"{}\"()",
                    c, ctor));
                if IN_FN.with(|v| *v.borrow()) {
                    FN_ALLOCAS.with(|f| f.borrow_mut()
                        .push((name.clone(), "pyobj".into())));
                    PY_SLOTS.with(|t| t.borrow_mut().push(name.clone()));
                    FN_PY.with(|t| t.borrow_mut().push(name.clone()));
                    b.silent();
                    b.line(format!(
                        "  store {{i32, i8*}}* %\"{}\", {{i32, i8*}}** %\"{}\"",
                        c, name));
                } else {
                    *sc += 1;
                    tail_push(format!(
                        "@\"{}\" = global {{i32, i8*}}* null", name));
                    PY_SLOTS.with(|t| t.borrow_mut().push(name.clone()));
                    b.silent();
                    b.line(format!(
                        "  store {{i32, i8*}}* %\"{}\", {{i32, i8*}}** @\"{}\"",
                        c, name));
                }
                return;
            }
        }
        // w = vocab[k]: str-element read via copy_into; the destination
        // auto-declares (str global) BEFORE the rhs (wordcount evidence)
        if rhs.head() == "subscript" && rhs.get(1).head() == "name" {
            let bn2 = rhs.get(1).get(1).str_of();
            if LST_SLOTS.with(|t| t.borrow().iter().any(|x| x == &bn2))
                && lst_elem_ty(&bn2) == "str" {
                *sc += 1;
                tail_push(format!("@\"{}\" = global i8* null", name));
                STR_SLOTS.with(|t| t.borrow_mut().push(name.clone()));
                let l = b.nx();
                b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, bn2));
                unsafe { SC_PTR = sc; }
                let k = b.expr_i64(&rhs.get(2), &global_slot);
                let d = b.nx();
                b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", d, name));
                let c = b.nx();
                b.line(format!(
                    "  %\"{}\" = call i8* @\"rawlist_str_copy_into\"(i8* %\"{}\", i64 {}, i8* %\"{}\")",
                    c, l, k, d));
                b.silent();
                b.line(format!("  store i8* %\"{}\", i8** @\"{}\"", c, name));
                return;
            }
        }
        // auto-declared locals from typed rhs (ch = src[pos], start = pos)
        let fs = F_SLOTS.with(|f| f.borrow().clone());
        let v = eval_mod(b, &rhs, &fs, sc);
        match v {
            Typed::Str(_) | Typed::PStr(_) => {
                FN_ALLOCAS.with(|f| f.borrow_mut()
                    .push((name.clone(), "str".into())));
                FN_S.with(|y| y.borrow_mut().push(name.clone()));
                let r = to_raw(b, v, sc);
                if rhs.head() == "subscript" { b.silent(); }
                TEMP_STRS.with(|t| t.borrow_mut().retain(|x| x != &r));
                let old = b.nx();
                b.line(format!(
                    "  %\"{}\" = load i8*, i8** %\"{}\"", old, name));
                b.silent();
                b.line(format!(
                    "  call void @\"rawstr_free\"(i8* %\"{}\")", old));
                b.silent();
                b.line(format!("  store i8* {}, i8** %\"{}\"", r, name));
            }
            Typed::F64(_) => {
                // float rhs auto-declares a float slot (mandelbrot/nbody)
                let r = to_f64(b, v);
                if IN_FN.with(|v| *v.borrow()) {
                    FN_ALLOCAS.with(|f| f.borrow_mut()
                        .push((name.clone(), "float".into())));
                    FN_F.with(|y| y.borrow_mut().push(name.clone()));
                    b.silent();
                    b.line(format!(
                        "  store double {}, double* %\"{}\"", r, name));
                } else {
                    *sc += 1;
                    tail_push(format!(
                        "@\"{}\" = global double {}", name, double_bits(0.0)));
                    F_SLOTS.with(|f| f.borrow_mut().push(name.clone()));
                    b.silent();
                    b.line(format!(
                        "  store double {}, double* @\"{}\"", r, name));
                }
            }
            Typed::Pyo(r) => {
                if IN_FN.with(|v| *v.borrow()) {
                    FN_ALLOCAS.with(|f| f.borrow_mut()
                        .push((name.clone(), "pyobj".into())));
                    PY_SLOTS.with(|t| t.borrow_mut().push(name.clone()));
                    FN_PY.with(|t| t.borrow_mut().push(name.clone()));
                    b.silent();
                    b.line(format!(
                        "  store {{i32, i8*}}* {}, {{i32, i8*}}** %\"{}\"",
                        r, name));
                } else {
                    *sc += 1;
                    tail_push(format!(
                        "@\"{}\" = global {{i32, i8*}}* null", name));
                    PY_SLOTS.with(|t| t.borrow_mut().push(name.clone()));
                    b.silent();
                    b.line(format!(
                        "  store {{i32, i8*}}* {}, {{i32, i8*}}** @\"{}\"",
                        r, name));
                }
            }
            Typed::Inst(r) => {
                // str-valued auto-decl (parse_string result): i8* slot;
                // the local pre-exists (null in prologue) so assignments
                // free the old value first (parse_object key evidence)
                if IN_FN.with(|v| *v.borrow()) {
                    FN_ALLOCAS.with(|f| f.borrow_mut()
                        .push((name.clone(), "str".into())));
                    FN_S.with(|y| y.borrow_mut().push(name.clone()));
                    // call result holds one temp slot before the old-value
                    // load (ref: call .121, silent .122, load key .123)
                    b.silent();
                    let old = b.nx();
                    b.line(format!(
                        "  %\"{}\" = load i8*, i8** %\"{}\"", old, name));
                    b.silent();
                    b.line(format!(
                        "  call void @\"rawstr_free\"(i8* %\"{}\")", old));
                    b.silent();
                    b.line(format!(
                        "  store i8* {}, i8** %\"{}\"", r, name));
                } else {
                    *sc += 1;
                    tail_push(format!(
                        "@\"{}\" = global i8* null", name));
                    STR_SLOTS.with(|t| t.borrow_mut().push(name.clone()));
                    b.silent();
                    b.line(format!(
                        "  store i8* {}, i8** @\"{}\"", r, name));
                }
            }
            Typed::I64(r) => {
                if IN_FN.with(|v| *v.borrow()) {
                    // function-local auto int: alloca, not a global
                    FN_ALLOCAS.with(|f| f.borrow_mut()
                        .push((name.clone(), "int".into())));
                    FN_I.with(|y| y.borrow_mut().push(name.clone()));
                    b.silent();
                    b.line(format!("  store i64 {}, i64* %\"{}\"", r, name));
                } else {
                    *sc += 1;
                    tail_push(format!("@\"{}\" = global i64 0", name));
                    b.silent();
                    b.line(format!("  store i64 {}, i64* @\"{}\"", r, name));
                }
            }
            _ => bail("auto decl type"),
        }
    } else if is_s || is_local_s(&name) {
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
        } else {
            // general str rhs: eval, free the old value, store new.
            // char1 rhs consumes ONE extra silent slot before the
            // old-value load (calc: .65 char1 -> .67 load ch)
            let fs = F_SLOTS.with(|f| f.borrow().clone());
            let was_char1 = rhs.head() == "subscript";
            let v = eval_mod(b, &rhs, &fs, sc);
            let r = to_raw(b, v, sc);
            if was_char1 { b.silent(); }
            TEMP_STRS.with(|t| t.borrow_mut().retain(|x| x != &r));
            let slot = if is_local_s(&name) { format!("%\"{}\"", name) }
                       else { format!("@\"{}\"", name) };
            let old = b.nx();
            b.line(format!("  %\"{}\" = load i8*, i8** {}", old, slot));
            b.silent();
            b.line(format!(
                "  call void @\"rawstr_free\"(i8* %\"{}\")", old));
            b.silent();
            b.line(format!("  store i8* {}, i8** {}", r, slot));
        }
    } else {
        if LST_SLOTS.with(|t| t.borrow().iter().any(|x| x == &name))
            || DCT_SLOTS.with(|t| t.borrow().iter().any(|x| x == &name)) {
            bail("assign to container");
        }
        // untyped container literals: dynamic pyobj (parse_array/object)
        if rhs.head() == "list" || rhs.head() == "dict" {
            let elems = rhs.items().get(1).cloned().unwrap_or(Val::Null);
            let empty = matches!(&elems, Val::List(v) if v.is_empty());
            if empty {
                let ctor = if rhs.head() == "list" { "create_list" }
                           else { "create_dict" };
                let c = b.nx();
                b.line(format!(
                    "  %\"{}\" = call {{i32, i8*}}* @\"{}\"()",
                    c, ctor));
                if IN_FN.with(|v| *v.borrow()) {
                    FN_ALLOCAS.with(|f| f.borrow_mut()
                        .push((name.clone(), "pyobj".into())));
                    PY_SLOTS.with(|t| t.borrow_mut().push(name.clone()));
                    FN_PY.with(|t| t.borrow_mut().push(name.clone()));
                    b.silent();
                    b.line(format!(
                        "  store {{i32, i8*}}* %\"{}\", {{i32, i8*}}** %\"{}\"",
                        c, name));
                } else {
                    *sc += 1;
                    tail_push(format!(
                        "@\"{}\" = global {{i32, i8*}}* null", name));
                    PY_SLOTS.with(|t| t.borrow_mut().push(name.clone()));
                    b.silent();
                    b.line(format!(
                        "  store {{i32, i8*}}* %\"{}\", {{i32, i8*}}** @\"{}\"",
                        c, name));
                }
                return;
            }
        }
        // w = vocab[k]: str-element read via copy_into; the destination
        // auto-declares (str global) BEFORE the rhs (wordcount evidence)
        if rhs.head() == "subscript" && rhs.get(1).head() == "name" {
            let bn = rhs.get(1).get(1).str_of();
            if LST_SLOTS.with(|t| t.borrow().iter().any(|x| x == &bn))
                && lst_elem_ty(&bn) == "str" {
                if !is_declared(&name) {
                    *sc += 1;
                    tail_push(format!("@\"{}\" = global i8* null", name));
                    STR_SLOTS.with(|t| t.borrow_mut().push(name.clone()));
                }
                let l = b.nx();
                b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, bn));
                unsafe { SC_PTR = sc; }
                let k = b.expr_i64(&rhs.get(2), &global_slot);
                let d = b.nx();
                b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", d, name));
                let c = b.nx();
                b.line(format!(
                    "  %\"{}\" = call i8* @\"rawlist_str_copy_into\"(i8* %\"{}\", i64 {}, i8* %\"{}\")",
                    c, l, k, d));
                b.silent();
                b.line(format!("  store i8* %\"{}\", i8** @\"{}\"", c, name));
                return;
            }
        }
        let fs = F_SLOTS.with(|f| f.borrow().clone());
        let v = eval_mod(b, &rhs, &fs, sc);
        if let Typed::F64(_) = v {
            // float rhs auto-declares a float global (SOLAR_MASS evidence)
            if !is_declared(&name) {
                *sc += 1;
                tail_push(format!(
                    "@\"{}\" = global double {}", name, double_bits(0.0)));
                F_SLOTS.with(|f| f.borrow_mut().push(name.clone()));
            }
            let r = to_f64(b, v);
            b.silent();
            b.line(format!("  store double {}, double* @\"{}\"", r, name));
            return;
        }
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
        // d[k] = d.get(k, def) + N idiom: entry slot pointer pattern
        let val = st.get(3);
        if dct_key_ty(&obj) == "str" && val.head() == "+"
            && val.get(1).head() == "call"
            && val.get(1).get(1).head() == "attribute"
            && val.get(1).get(1).get(2).str_of() == "get" {
            let dl = b.nx();
            b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", dl, obj));
            let fs = F_SLOTS.with(|f| f.borrow().clone());
            let kr = if let Some((bname, sl)) = as_slice_sub(&st.get(2)) {
                emit_slice_view(b, &bname, &sl, sc)
            } else {
                let kv = eval_mod(b, &st.get(2), &fs, sc);
                to_raw(b, kv, sc)
            };
            let gargs = val.get(1).get(2).items();
            if gargs.len() != 2
                || !matches!(gargs[1].get(1), Val::Int(_)) { bail("get idiom default"); }
            let en = b.nx();
            b.line(format!(
                "  %\"{}\" = call i8* @\"rawdict_str_entry\"(i8* %\"{}\", i8* {}, i64 {})",
                en, dl, kr, gargs[1].get(1).int_of()));
            let bc = b.nx();
            b.line(format!("  %\"{}\" = bitcast i8* %\"{}\" to i64*", bc, en));
            let ld = b.nx();
            b.line(format!("  %\"{}\" = load i64, i64* %\"{}\"", ld, bc));
            let rhs_v = eval_mod(b, &val.get(2), &fs, sc);
            let Typed::I64(r) = rhs_v else { bail("get idiom rhs") };
            let res = b.checked_raw(&format!("%\"{}\"", ld), &r, "+", sc);
            b.silent();
            b.line(format!("  store i64 {}, i64* %\"{}\"", res, bc));
            return;
        }
        if dct_key_ty(&obj) == "str" {
            // o[key] = value on a str-keyed dict. Value order: obj, then
            // value, then key; rawdict_str_set. A Json value (tagged block
            // pointer) is ptrtoint'd into the slot's i64 bits
            // (jsonparse_json parse_object o[key]=parse_value evidence)
            let l = b.nx();
            b.line(format!("  %\"{}\" = load i8*, i8** {}", l, dct_slot(&obj)));
            let fs = F_SLOTS.with(|f| f.borrow().clone());
            let vv = eval_mod(b, &st.get(3), &fs, sc);
            let vbits = match vv {
                Typed::Inst(r) | Typed::Str(r) => {
                    let pt = b.nx();
                    b.line(format!("  %\"{}\" = ptrtoint i8* {} to i64", pt, r));
                    format!("%\"{}\"", pt)
                }
                Typed::I64(r) => r,
                _ => bail("dict str value"),
            };
            let kr = {
                let kv = eval_mod(b, &st.get(2), &fs, sc);
                match kv {
                    Typed::Str(r) | Typed::Inst(r) => r,
                    Typed::PStr(_) => to_raw(b, kv, sc),
                    _ => bail("dict str key"),
                }
            };
            b.silent();
            b.line(format!(
                "  call void @\"rawdict_str_set\"(i8* %\"{}\", i8* {}, i64 {})",
                l, kr, vbits));
            return;
        }
        let l = b.nx();
        b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, obj));
        let v = b.expr_i64_raw(&st.get(3), &global_slot, sc);
        let k = b.expr_i64_raw(&st.get(2), &global_slot, sc);
        b.silent();
        b.line(format!(
                "  call void @\"rawdict_set\"(i8* %\"{}\", i64 {}, i64 {})",
            l, k, v));
    } else if is_py(&obj) {
        // dynamic store: pyobj_subscript_set(obj, pykey, pyval)
        let fs = F_SLOTS.with(|f| f.borrow().clone());
        let dl = b.nx();
        b.line(format!(
            "  %\"{}\" = load {{i32, i8*}}*, {{i32, i8*}}** {}",
            dl, py_slot(&obj)));
        let kr = {
            let kv = eval_mod(b, &st.get(2), &fs, sc);
            match kv {
                Typed::Str(r) | Typed::Inst(r) => r,
                Typed::PStr(_) => to_raw(b, kv, sc),
                _ => bail("pyobj store key"),
            }
        };
        let ps = b.nx();
        b.line(format!(
            "  %\"{}\" = call {{i32, i8*}}* @\"rawstr_to_pystr\"(i8* {})",
            ps, kr));
        let vv = eval_mod(b, &st.get(3), &fs, sc);
        let Typed::Pyo(pv) = vv else { bail("pyobj store val") };
        b.silent();
        b.line(format!(
            "  call void @\"pyobj_subscript_set\"({{i32, i8*}}* %\"{}\", {{i32, i8*}}* %\"{}\", {{i32, i8*}}* {})",
            dl, ps, pv));
    } else if LST_SLOTS.with(|t| t.borrow().iter().any(|f| f == &obj))
        || FN_L.with(|t| t.borrow().iter().any(|(k, _)| k == &obj)) {
        let l = b.nx(); // obj load, then key eval, then value eval
        b.line(format!("  %\"{}\" = load i8*, i8** {}",
            l, lst_slot(&obj)));
        let k = b.expr_i64_raw(&st.get(2), &global_slot, sc);
        let elem = lst_elem_ty(&obj);
        let fs = F_SLOTS.with(|f| f.borrow().clone());
        unsafe { SC_PTR = sc; }
        let v = if elem == "float" {
            let v = eval_expr(b, &st.get(3), &global_slot, &global_slot,
                              sc, &fs);
            let Typed::F64(r) = v else { bail("list set value type") };
            r
        } else {
            b.expr_i64_raw(&st.get(3), &global_slot, sc)
        };
        b.list_set(&format!("%\"{}\"", l), &k, &v, sc, &elem);
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
                        .any(|f| f == &obj))
                    && !FN_L.with(|t| t.borrow().iter()
                        .any(|(k, _)| k == &obj))
                    && !is_py(&obj) { bail("append target"); }
                let args = st.get(2).items();
                if args.len() != 1 { bail("append arity"); }
                let l = b.nx(); // object load first, then arg eval
                if !is_py(&obj) {
                b.line(format!("  %\"{}\" = load i8*, i8** {}",
                    l, lst_slot(&obj)));
                let elem = lst_elem_ty(&obj);
                let fs = F_SLOTS.with(|f| f.borrow().clone());
                let v = eval_mod(b, &args[0], &fs, sc);
                if elem == "str" {
                    // str append: to_raw, rawstr_copy, rawlist_str_push
                    let r = to_raw(b, v, sc);
                    let cp = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i8* @\"rawstr_copy\"(i8* {})", cp, r));
                    let c = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i64 @\"rawlist_str_push\"(i8* %\"{}\", i8* %\"{}\")",
                        c, l, cp));
                } else if elem == "float" {
                    let r = to_f64(b, v);
                    let ib = b.nx();
                    b.line(format!(
                        "  %\"{}\" = bitcast double {} to i64", ib, r));
                    let c = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i64 @\"rawlist_push\"(i8* %\"{}\", i64 %\"{}\")",
                        c, l, ib));
                } else if let Typed::Inst(r) = &v {
                    // instance elements push as i64 (ptrtoint)
                    let pt = b.nx();
                    b.line(format!(
                        "  %\"{}\" = ptrtoint i8* {} to i64", pt, r));
                    let c = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i64 @\"rawlist_push\"(i8* %\"{}\", i64 %\"{}\")",
                        c, l, pt));
                } else {
                    let Typed::I64(r) = v else { bail("append type") };
                    let c = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i64 @\"rawlist_push\"(i8* %\"{}\", i64 {})",
                        c, l, r));
                }
                } else {
                    // dynamic append: list_append(pyobj, pyobj)
                    b.line(format!(
                        "  %\"{}\" = load {{i32, i8*}}*, {{i32, i8*}}** {}",
                        l, py_slot(&obj)));
                    let fs2 = F_SLOTS.with(|f| f.borrow().clone());
                    let v = eval_mod(b, &args[0], &fs2, sc);
                    let Typed::Pyo(r) = v else { bail("py append arg") };
                    let c = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call {{i32, i8*}}* @\"list_append\"({{i32, i8*}}* %\"{}\", {{i32, i8*}}* {})",
                        c, l, r));
                }
            }
            "call" => {
                // bare expression statement: valued call, discard result
                let fs = F_SLOTS.with(|f| f.borrow().clone());
                let _ = eval_mod(b, &st, &fs, sc);
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
                LOOP_DEPTH.with(|d| *d.borrow_mut() += 1);
                conv_block(b, &body, loops, sc);
                LOOP_DEPTH.with(|d| *d.borrow_mut() -= 1);
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
                LOOP_DEPTH.with(|d| *d.borrow_mut() += 1);
                conv_block(b, &body, loops, sc);
                LOOP_DEPTH.with(|d| *d.borrow_mut() -= 1);
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
                LOOP_DEPTH.with(|d| *d.borrow_mut() += 1);
                let t_term = conv_block(b, &then_body, loops, sc);
                LOOP_DEPTH.with(|d| *d.borrow_mut() -= 1);
                if !t_term {
                    b.silent();
                    b.line(format!("  br label %\"{}\"", m_lbl));
                }
                b.pos(e_b);
                LOOP_DEPTH.with(|d| *d.borrow_mut() += 1);
                let e_term = conv_block(b, &orelse, loops, sc);
                LOOP_DEPTH.with(|d| *d.borrow_mut() -= 1);
                if !e_term {
                    b.silent();
                    b.line(format!("  br label %\"{}\"", m_lbl));
                }
                b.pos(m_b);
            }
            "return" if IN_FN.with(|v| *v.borrow()) => {
                let rty = FN_RET.with(|r| r.borrow().clone());
                let fs = F_SLOTS.with(|f| f.borrow().clone());
                let v = eval_mod(b, &st.get(1), &fs, sc);
                // epilogue: free non-param str locals before returning;
                // a str local that IS the return value frees itself in
                // the ret copy chain (jsonparse parse_string evidence)
                let ret_str_local = if rty == "str" && st.get(1).head() == "name"
                    && is_local_s(&st.get(1).get(1).str_of()) {
                    Some(st.get(1).get(1).str_of()) } else { None };
                let locals = FN_S.with(|y| y.borrow().clone());
                // Json returns box first, then free the str locals (the
                // tagged_new_ptr/copy precede the ch free, parse_value
                // evidence); other returns free before the value dispatch
                if rty != "json" {
                for nm in locals.iter() {
                    if Some(nm.as_str()) == ret_str_local.as_deref() {
                        continue;
                    }
                    if FN_PARAM_NAMES.with(|p| p.borrow().contains(nm)) {
                        continue;
                    }
                    let lf = b.nx();
                    b.line(format!(
                        "  %\"{}\" = load i8*, i8** %\"{}\"", lf, nm));
                    b.silent();
                    b.line(format!(
                        "  call void @\"rawstr_free\"(i8* %\"{}\")", lf));
                }
                }
                if rty == "float" {
                    let r = to_f64(b, v);
                    b.silent();
                    b.line(format!("  ret double {}", r));
                } else if let Typed::Pyo(r) = &v {
                    b.silent();
                    b.line(format!(
                        "  ret {{i32, i8*}}* {}", r));
                } else if rty == "json" {
                    // Json return: box the value into a tagged block, THEN
                    // free the str locals (ch free follows tagged_new_ptr,
                    // parse_value evidence)
                    macro_rules! free_str_locals {
                        ($bb:expr) => {
                            for nm in locals.iter() {
                                if FN_PARAM_NAMES.with(|p| p.borrow().contains(nm)) {
                                    continue;
                                }
                                let lf = $bb.nx();
                                $bb.line(format!(
                                    "  %\"{}\" = load i8*, i8** %\"{}\"", lf, nm));
                                $bb.silent();
                                $bb.line(format!(
                                    "  call void @\"rawstr_free\"(i8* %\"{}\")", lf));
                            }
                        };
                    }
                    let src = &st.get(1);
                    let callee_json = src.head() == "call"
                        && src.get(1).head() == "name"
                        && FN_SIGS.with(|m| m.borrow().iter().any(|(k, _, r)|
                            *k == src.get(1).get(1).str_of() && r == "json"));
                    if callee_json {
                        let r = match &v {
                            Typed::Inst(r) | Typed::Str(r) => r.clone(),
                            _ => bail("json ret callee"),
                        };
                        free_str_locals!(b);
                        b.silent();
                        b.line(format!("  ret i8* {}", r));
                    } else {
                        // decide the box kind from the SOURCE type: a call
                        // uses the callee's return type (parse_string->str
                        // yields Inst, not Str), a local name uses its
                        // container registration (list[Json]/dict[Json])
                        let callee_rty = if src.head() == "call"
                            && src.get(1).head() == "name" {
                            FN_SIGS.with(|m| m.borrow().iter()
                                .find(|(k, _, _)| *k == src.get(1).get(1).str_of())
                                .map(|(_, _, r)| r.clone()))
                        } else { None };
                        let (tag, is_ptr, copy) = match callee_rty.as_deref() {
                            Some("str") => (4, true, true),
                            Some("int") => (1, false, false),
                            _ => match &v {
                                Typed::I64(_) => (1, false, false),
                                Typed::Str(_) => (4, true, true),
                                _ if src.head() == "name"
                                    && FN_L.with(|l| l.borrow().iter().any(|(k, _)|
                                        *k == src.get(1).str_of())) => (5, true, false),
                                _ if src.head() == "name"
                                    && FN_D.with(|l| l.borrow().iter()
                                        .any(|k| *k == src.get(1).str_of())) => (6, true, false),
                                _ => bail("json ret src"),
                            },
                        };
                        let r = match &v {
                            Typed::I64(r) => r.clone(),
                            Typed::Str(r) | Typed::Inst(r) => r.clone(),
                            _ => bail("json ret val"),
                        };
                        if is_ptr {
                            // str payload is copied first; list/dict not
                            let r2 = if copy {
                                let cp = b.nx();
                                b.line(format!(
                                    "  %\"{}\" = call i8* @\"rawstr_copy\"(i8* {})", cp, r));
                                format!("%\"{}\"", cp)
                            } else { r };
                            let c = b.nx();
                            b.line(format!(
                                "  %\"{}\" = call i8* @\"tagged_new_ptr\"(i32 {}, i8* {})",
                                c, tag, r2));
                            free_str_locals!(b);
                            b.silent();
                            b.line(format!("  ret i8* %\"{}\"", c));
                        } else {
                            let c = b.nx();
                            b.line(format!(
                                "  %\"{}\" = call i8* @\"tagged_new_scalar\"(i32 {}, i64 {})",
                                c, tag, r));
                            free_str_locals!(b);
                            b.silent();
                            b.line(format!("  ret i8* %\"{}\"", c));
                        }
                    }
                } else if rty == "str" && st.get(1).head() == "name"
                    && is_local_s(&st.get(1).get(1).str_of()) {
                    // str local return reuses the eval load:
                    // copy(eval) -> reload -> free -> ret copy
                    let nm = st.get(1).get(1).str_of();
                    let Typed::Str(r0) = &v else { bail("ret str ref") };
                    let cp = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i8* @\"rawstr_copy\"(i8* {})",
                        cp, r0));
                    let l2 = b.nx();
                    b.line(format!(
                        "  %\"{}\" = load i8*, i8** %\"{}\"", l2, nm));
                    b.silent();
                    b.line(format!(
                        "  call void @\"rawstr_free\"(i8* %\"{}\")", l2));
                    b.silent();
                    b.line(format!("  ret i8* %\"{}\"", cp));
                } else if rty.starts_with("inst:") || rty == "str"
                    || rty.starts_with("list:") {
                    match v {
                        Typed::Inst(r) | Typed::Str(r) => {
                            b.silent();
                            b.line(format!("  ret i8* {}", r));
                        }
                        Typed::I64(r) => {
                            let pt = b.nx();
                            b.line(format!(
                                "  %\"{}\" = inttoptr i64 {} to i8*",
                                pt, r));
                            b.silent();
                            b.line(format!(
                                "  ret i8* %\"{}\"", pt));
                        }
                        _ => bail("ret ptr type"),
                    }
                } else {
                    let Typed::I64(r) = v else { bail("ret type") };
                    b.silent();
                    b.line(format!("  ret i64 {}", r));
                }
                return true;
            }
            "break" => {
                let end = loops.last().cloned()
                    .unwrap_or_else(|| bail("break outside loop"));
                b.silent();
                b.line(format!("  br label %\"{}\"", end));
                return true;
            }
            "enum_def" => {
                *sc += 1; // registered by the prescan
            }
            "class_def" => {
                // instance-domain classes occupy a global slot (calc);
                // pyobj dynamic classes register only a layout (jsonparse)
                let cn = st.get(1).str_of();
                if !is_dyn_class(&cn) { *sc += 1; }
            }
            "match" => {
                // scrutinee read once, then a case_next chain; wildcard
                // cases br through case_next.N to match_end (calc)
                let fs = F_SLOTS.with(|f| f.borrow().clone());
                let sv = eval_mod(b, &st.get(1), &fs, sc);
                let cases = st.get(2).items();
                let end_lbl = b.uniq_label("match_end");
                let pyo_ref = match &sv {
                    Typed::Pyo(r) => Some(r.clone()),
                    _ => None,
                };
                let vref = match sv.clone() {
                    Typed::I64(r) => r,
                    _ => {
                        if pyo_ref.is_none() {
                            bail("match scrutinee");
                        }
                        String::new()
                    }
                };
                MATCH_END.with(|m| m.borrow_mut().push(end_lbl.clone()));
                for (ci, c) in cases.iter().enumerate() {
                    // match_case = [match_case, pattern, guard, body]
                    let pat = c.get(1);
                    let cbody = c.get(3).items();
                    let body_lbl = b.uniq_label("case_body");
                    let next_lbl = b.uniq_label("case_next");
                    if ci == 0 {
                        // match_end created BEFORE case_body (ref order)
                        let eb = b.add_block(&end_lbl);
                        let _ = eb;
                        let bb = b.add_block(&body_lbl);
                        let _ = bb;
                        let nb = b.add_block(&next_lbl);
                        let _ = nb;
                    } else {
                        let bb = b.add_block(&body_lbl);
                        let _ = bb;
                        let nb = b.add_block(&next_lbl);
                        let _ = nb;
                    }
                    if pat.head() == "match_class" {
                        // dynamic class: pyobj_instance_cid == CID
                        let pr = pyo_ref.clone().unwrap_or_else(|| {
                            eprintln!("mc fail, scrut head={}",
                                st.get(1).head());
                            bail("match_class scrutinee") });
                        let cn = pat.get(1).get(1).str_of();
                        let cid = b.nx();
                        b.line(format!(
                            "  %\"{}\" = call i64 @\"pyobj_instance_cid\"({{i32, i8*}}* {})",
                            cid, pr));
                        let eq = b.nx();
                        b.line(format!(
                            "  %\"{}\" = icmp eq i64 %\"{}\", {}",
                            eq, cid, class_cid(&cn)));
                        b.silent();
                        b.line(format!(
                            "  br i1 %\"{}\", label %\"{}\", label %\"{}\"",
                            eq, body_lbl, next_lbl));
                        // captures in the body block: instance_ptr + field
                        let cap_fields = pat.get(3).items();
                        let cap_binds = pat.get(4).items();
                        let bi = b.blocks.iter()
                            .position(|(l, _)| l == &body_lbl)
                            .unwrap_or_else(|| bail("case body missing"));
                        b.pos(bi);
                        let ptr = b.nx();
                        b.line(format!(
                            "  %\"{}\" = call i8* @\"pyobj_instance_ptr\"({{i32, i8*}}* {})",
                            ptr, pr));
                        let fields = class_fields(&cn)
                            .unwrap_or_else(|| bail("class fields"));
                        for (fi, bind) in cap_binds.iter().enumerate() {
                            *sc += 1; // capture gvar occupies a global slot
                            let bname = bind.get(2).str_of();
                            let fname = cap_fields.get(fi)
                                .map(|v| v.str_of()).unwrap_or_default();
                            let (off, fty) = fields.iter()
                                .position(|(f, _)| f == &fname)
                                .map(|i| ((i * 8) as i64, fields[i].1.clone()))
                                .unwrap_or_else(|| bail("capture field"));
                            let gp = b.nx();
                            b.line(format!(
                                "  %\"{}\" = getelementptr i8, i8* %\"{}\", i64 {}",
                                gp, ptr, off));
                            match fty.as_str() {
                                "str" => {
                                    let bc = b.nx();
                                    b.line(format!(
                                        "  %\"{}\" = bitcast i8* %\"{}\" to i8**", bc, gp));
                                    let ld = b.nx();
                                    b.line(format!(
                                        "  %\"{}\" = load i8*, i8** %\"{}\"", ld, bc));
                                    // capture -> raw str global, COPY first
                                    // (case JStr(v=w) evidence)
                                    let cp = b.nx();
                                    b.line(format!(
                                        "  %\"{}\" = call i8* @\"rawstr_copy\"(i8* %\"{}\")",
                                        cp, ld));
                                    tail_push(format!(
                                        "@\"{}\" = global i8* null", bname));
                                    STR_SLOTS.with(|t| t.borrow_mut().push(bname.clone()));
                                    b.silent();
                                    b.line(format!(
                                        "  store i8* %\"{}\", i8** @\"{}\"", cp, bname));
                                }
                                "list" | "dict" => {
                                    let bc = b.nx();
                                    b.line(format!(
                                        "  %\"{}\" = bitcast i8* %\"{}\" to {{i32, i8*}}**", bc, gp));
                                    let ld = b.nx();
                                    b.line(format!(
                                        "  %\"{}\" = load {{i32, i8*}}*, {{i32, i8*}}** %\"{}\"", ld, bc));
                                    tail_push(format!(
                                        "@\"{}\" = global {{i32, i8*}}* null", bname));
                                    PY_SLOTS.with(|t| t.borrow_mut().push(bname.clone()));
                                    b.silent();
                                    b.line(format!(
                                        "  store {{i32, i8*}}* %\"{}\", {{i32, i8*}}** @\"{}\"", ld, bname));
                                }
                                _ => {
                                    let bc = b.nx();
                                    b.line(format!(
                                        "  %\"{}\" = bitcast i8* %\"{}\" to i64*", bc, gp));
                                    let ld = b.nx();
                                    b.line(format!(
                                        "  %\"{}\" = load i64, i64* %\"{}\"", ld, bc));
                                    tail_push(format!(
                                        "@\"{}\" = global i64 0", bname));
                                    b.silent();
                                    b.line(format!(
                                        "  store i64 %\"{}\", i64* @\"{}\"", ld, bname));
                                }
                            }
                        }
                        // continue converting the case body after captures
                        CASE_DEPTH.with(|c| c.borrow_mut()
                            .push(LOOP_DEPTH.with(|d| *d.borrow())));
                        conv_block(b, &cbody, loops, sc);
                        CASE_DEPTH.with(|c| c.borrow_mut().pop());
                        let ni = b.blocks.iter()
                            .position(|(l, _)| l == &next_lbl)
                            .unwrap_or_else(|| bail("case next missing"));
                        b.pos(ni);
                        continue;
                    }
                    if pat.head() == "match_value" {
                        let mv = pat.get(1);
                        let variant = mv.get(2).str_of();
                        let enum_ = mv.get(1).get(1).str_of();
                        let k = enum_val(&enum_, &variant)
                            .unwrap_or_else(|| bail("enum variant"));
                        let eq = b.nx();
                        b.line(format!(
                            "  %\"{}\" = icmp eq i64 {}, {}",
                            eq, vref, k));
                        b.silent();
                        b.line(format!(
                            "  br i1 %\"{}\", label %\"{}\", label %\"{}\"",
                            eq, body_lbl, next_lbl));
                    } else {
                        // wildcard: case_next brs to the wildcard BODY
                        b.silent();
                        b.line(format!("  br label %\"{}\"", body_lbl));
                    }
                    let bi = b.blocks.iter().position(|(l, _)| l == &body_lbl)
                        .unwrap_or_else(|| bail("case body missing"));
                    b.pos(bi);
                    CASE_DEPTH.with(|c| c.borrow_mut()
                        .push(LOOP_DEPTH.with(|d| *d.borrow())));
                    conv_block(b, &cbody, loops, sc);
                    CASE_DEPTH.with(|c| c.borrow_mut().pop());
                    let ni = b.blocks.iter()
                        .position(|(l, _)| l == &next_lbl)
                        .unwrap_or_else(|| bail("case next missing"));
                    b.pos(ni);
                }
                // trailing case_next brs to match_end
                b.silent();
                b.line(format!("  br label %\"{}\"", end_lbl));
                MATCH_END.with(|m| m.borrow_mut().pop());
                let e_idx = b.blocks.iter()
                    .position(|(l, _)| l == &end_lbl);
                let is_last = i + 1 >= stmts.len();
                if let Some(i2) = e_idx {
                    b.pos(i2);
                    if is_last && IN_FN.with(|v| *v.borrow()) {
                        // trailing match: typed default ret in match_end;
                        // the parent-merge branch (if any) is emitted by
                        // the enclosing block's fallthrough rule
                        let rty = FN_RET.with(|r| r.borrow().clone());
                        b.silent();
                        match rty.as_str() {
                            "float" => b.line(format!(
                                "  ret double {}", double_bits(0.0))),
                            t if t.starts_with("inst:") || t == "str"
                                || t.starts_with("list:") =>
                                b.line("  ret i8* null".into()),
                            "none" | "pyobj" =>
                                b.line("  ret {i32, i8*}* null".into()),
                            _ => b.line("  ret i64 0".into()),
                        }
                        return true;
                    }
                }
                // match_end is a merge block: following stmts flow here;
                // when this match was nested, the parent's fallthrough
                // rule appends br match_end.<parent> to this block
            }
"raise" => {
                // raise SystemExit(N): free str locals, trunc, exit
                let locals = FN_S.with(|y| y.borrow().clone());
                for nm in locals.iter() {
                    if FN_PARAM_NAMES.with(|p| p.borrow().contains(nm)) {
                        continue;
                    }
                    let lf = b.nx();
                    b.line(format!(
                        "  %\"{}\" = load i8*, i8** %\"{}\"", lf, nm));
                    b.silent();
                    b.line(format!(
                        "  call void @\"rawstr_free\"(i8* %\"{}\")", lf));
                }
                let arg = st.get(1);
                if arg.head() != "call"
                    || arg.get(1).get(1).str_of() != "SystemExit" {
                    bail("raise target");
                }
                let a = &arg.get(2).items()[0];
                if !matches!(a.get(1), Val::Int(_)) { bail("exit arg"); }
                let fs = F_SLOTS.with(|f| f.borrow().clone());
                let v = eval_mod(b, a, &fs, sc);
                let Typed::I64(r) = v else { bail("exit arg type") };
                let t = b.nx();
                b.line(format!("  %\"{}\" = trunc i64 {} to i32", t, r));
                b.silent();
                b.line(format!("  call void @\"exit\"(i32 %\"{}\")", t));
                b.silent();
                b.line("  unreachable".into());
                return true;
            }
            "attribute_aug_assign" => {
                // frontend-desugared self.f op= v -> attribute-target aug
                let rebuilt = Val::List(vec![
                    Val::Str("aug_assign".into()),
                    Val::List(vec![Val::Str("attribute".into()),
                        st.get(1).clone(), st.get(2).clone()]),
                    st.get(3).clone(), st.get(4).clone()]);
                conv_aug_assign(b, &rebuilt, sc, &global_slot);
            }
            "func_def" => {
                // def main consumes TWO slots: main + __silu_user_main
                *sc += 1;
                if st.get(1).str_of() == "main" { *sc += 1; }
                FUNC_DEFS.with(|f| f.borrow_mut().push(st.clone()));
            }
            _ => bail(st.head()),
        }
        i += 1;
    }
    // statements exhausted inside a case body: fall through to the
    // innermost match merge unless the current block already terminates.
    // Only case bodies do this; a while body is closed by the loop's own
    // back-branch (panic_ok vs while_cond evidence in jsonparse main)
    let in_case = CASE_DEPTH.with(|c| c.borrow().last().cloned())
        .map(|d| d == LOOP_DEPTH.with(|l| *l.borrow()))
        .unwrap_or(false);
    if in_case {
        if let Some(me) = MATCH_END.with(|m| m.borrow().last().cloned()) {
            let term = b.blocks[b.cur].1.last()
                .map(|l| l.trim_start().starts_with("br ")
                    || l.trim_start().starts_with("ret ")
                    || l.trim_start().starts_with("unreachable"))
                .unwrap_or(false);
            if !term {
                b.silent();
                b.line(format!("  br label %\"{}\"", me));
            }
        }
    }
    false
}

// module-level walk (main body). Returns fn_defs; globals land in TAIL.
fn walk_module(stmts: &[Val], sc: &mut usize) -> Vec<Val> {
    let mut b = FnB::new(1); // .1 = main ret slot
    let mut loops: Vec<String> = Vec::new();
    conv_block(&mut b, stmts, &mut loops, sc);
    let has_user_main = stmts.iter().any(|st| {
        st.head() == "func_def" && st.get(1).str_of() == "main"
    });
    if has_user_main {
        // main wraps __silu_user_main: call, trunc, ret
        let c = b.nx();
        b.line(format!(
            "  %\"{}\" = call i64 @\"__silu_user_main\"()", c));
        let t = b.nx();
        b.line(format!("  %\"{}\" = trunc i64 %\"{}\" to i32", t, c));
        b.silent();
        b.line(format!("  ret i32 %\"{}\"", t));
    } else {
        b.silent(); // ret
        b.line("  ret i32 0".into());
    }
    let mut out = b.render("define i32 @\"main\"()\n");
    let mut alloca_lines = String::new();
    MAIN_ALLOCAS.with(|m| {
        for vn in m.borrow().iter().rev() {
            alloca_lines.push_str(&format!(
                "  %\"{}\" = alloca {{i64, i64, i8*, i64}}\n", vn));
        }
    });
    if let Some(epos) = out.find("entry:\n") {
        out.insert_str(epos + "entry:\n".len(), &alloca_lines);
    }
    unsafe {
        MAIN_OUT = Some(out);
    }
    FUNC_DEFS.with(|f| f.borrow().clone())
}

static mut MAIN_OUT: Option<String> = None;

// convert one function: params + body via conv_block with the FN_*
// context (locals shadow globals); allocas splice in reverse
// first-appearance order (params first) after the entry label
fn convert_func(fd: &Val, sc: &mut usize) -> String {
    let params = fd.get(2).items();
    let annos = fd.get(4).items();
    let ret_anno = fd.get(5);
    let body = fd.get(3).items();
    let mut name = fd.get(1).str_of();
    if name == "main" { name = "__silu_user_main".into(); }

    let mut atys = Vec::new();
    for (p, a) in params.iter().zip(annos.iter()) {
        if p.str_of().is_empty() { bail("param name"); }
        if a.head() == "name" {
            let t = a.get(1).str_of();
            if t != "int" && t != "float" && !is_class(&t) && t != "str"
                && !is_enum(&t) { bail("param type"); }
            if is_class(&t) { atys.push(format!("inst:{}", t)); }
            else if t == "str" { atys.push("str".into()); }
            else if is_enum(&t) { atys.push("int".into()); }
            else { atys.push(t.to_string()); }
        } else if a.head() == "subscript"
            && a.get(1).get(1).str_of() == "list" {
            atys.push(format!("list:{}", a.get(2).get(1).str_of()));
        } else { bail("param type"); }
    }
    // missing return annotation -> infer from return statements
    // (parse_string -> str i8* + alwaysinline; parse_value -> pyobj)
    let rty = if matches!(ret_anno, Val::Null) {
        let inferred = infer_ret(&body, &params, &annos);
        match inferred.as_str() {
            "str" => "str".to_string(),
            "int" => "int".to_string(),
            "float" => "float".to_string(),
            "pyobj" => "pyobj".to_string(),
            _ => "none".to_string(),
        }
    }
              else if ret_anno.head() == "subscript"
                  && ret_anno.get(1).get(1).str_of() == "list" {
                  let el = ret_anno.get(2).get(1).str_of();
                  format!("list:{}", if el == "Json" { "json".into() } else { el })
              }
              else {
                  let t = ret_anno.get(1).str_of();
                  if t == "Json" { "json".to_string() }
                  else {
                  if t != "int" && t != "float" && !is_class(&t) && t != "str" {
                      bail("ret type");
                  }
                  if is_class(&t) { format!("inst:{}", t) } else { t.to_string() }
                  }
              };

    FN_I.with(|f| *f.borrow_mut() = Vec::new());
    FN_F.with(|f| *f.borrow_mut() = Vec::new());
    FN_L.with(|f| *f.borrow_mut() = Vec::new());
    FN_PY.with(|f| *f.borrow_mut() = Vec::new());
    FN_D.with(|f| *f.borrow_mut() = Vec::new());
    FN_TY.with(|y| *y.borrow_mut() = Vec::new());
    FN_S.with(|y| *y.borrow_mut() = Vec::new());
    FN_B.with(|y| *y.borrow_mut() = Vec::new());
    FN_STOR.with(|y| *y.borrow_mut() = Vec::new());
    TEMP_STRS.with(|t| *t.borrow_mut() = Vec::new());
    FN_ALLOCAS.with(|f| *f.borrow_mut() = Vec::new());
    FN_PARAMS.with(|f| *f.borrow_mut() = Vec::new());
    FN_PARAM_NAMES.with(|f| *f.borrow_mut() = params.iter()
        .map(|p| p.str_of()).collect());
    FN_RET.with(|r| *r.borrow_mut() = rty.to_string());
    IN_FN.with(|v| *v.borrow_mut() = true);

    let n = params.len();
    let arg_ll = |t: &str| match t {
        "float" => "double",
        t if t.starts_with("list:") || t.starts_with("inst:")
            || t == "str" || t == "json" => "i8*",
        "pyobj" => "{i32, i8*}*",
        _ => "i64",
    };
    let rty_ll = match rty.as_str() {
        "pyobj" => "{i32, i8*}*",
        "float" => "double", "none" => "{i32, i8*}*",
        t if t.starts_with("inst:") || t == "str" || t == "json"
            || t.starts_with("list:") => "i8*",
        _ => "i64",
    };
    let header = format!(
        "define internal {} @\"{}\"({}){}\n",
        rty_ll, name,
        params.iter().zip(atys.iter()).enumerate()
            .map(|(i, (p, t))| format!("{} %\".{}\"",
                arg_ll(t), i + 1))
            .collect::<Vec<_>>().join(", "),
        if rty == "none" || rty == "pyobj" { "" }
        else { " alwaysinline" });

    let mut b = FnB::new(n + 1); // .1..N args, .N+1 ret slot
    // container params: alloca+store pairs in the splice, forward order
    let mut container_pairs = String::new();
    // owned str params (whole-use: slice base / len arg / by-name
    // compare) flip the prologue to the split form: params REVERSED
    // (str: alloca+null+store, container: bare alloca), container
    // stores deferred forward (jsonparse evidence)
    fn str_owned(body: &[Val], pn: &str) -> bool {
        fn scan(v: &Val, pn: &str) -> bool {
            if let Val::List(items) = v {
                let h = v.head();
                if h == "subscript" && v.get(1).head() == "name"
                    && v.get(1).get(1).str_of() == pn
                    && v.get(2).head() == "slice" { return true; }
                if h == "call" && v.get(1).head() == "name"
                    && v.get(1).get(1).str_of() == "len" {
                    let ia = v.get(2).items();
                    if ia.len() == 1 && ia[0].head() == "name"
                        && ia[0].get(1).str_of() == pn { return true; }
                }
                if (h == "==" || h == "!=")
                    && v.get(1).head() == "name"
                    && v.get(1).get(1).str_of() == pn
                    && v.get(2).head() == "const"
                    && matches!(v.get(2).get(1), Val::Str(_)) { return true; }
                for i in items { if scan(i, pn) { return true; } }
            }
            false
        }
        scan(&Val::List({
            let mut v = vec![Val::Str("body".into())];
            v.extend_from_slice(body);
            v
        }), pn)
    }
    SPLIT_FORM.with(|x| *x.borrow_mut() = false);
    // split form (reversed params, str null-init) applies when an owned
    // str param is detected (slice/len/by-name compare) OR the function
    // carries an explicit return annotation (typed path: _declare_var
    // null-inits every RAWSTR param). pyobj-returning functions without
    // an annotation keep the plain prologue (jsonparse.si parse_value vs
    // jsonparse_json parse_value evidence)
    let has_ret_anno = !matches!(ret_anno, Val::Null)
        && params.iter().zip(atys.iter()).any(|(_, t)| t == "str");
    let any_owned = params.iter().zip(atys.iter())
        .any(|(p, t)| t == "str" && str_owned(&body, &p.str_of()))
        || has_ret_anno;
    if !any_owned {
    for (i, (p, t)) in params.iter().zip(atys.iter()).enumerate() {
        if t.starts_with("list:") {
            FN_L.with(|f| f.borrow_mut()
                .push((p.str_of(), t.split(':').nth(1).unwrap_or("int").to_string())));
            container_pairs.push_str(&format!(
                "  %\"{}\" = alloca i8*\n  store i8* %\".{}\", i8** %\"{}\"\n",
                p.str_of(), i + 1, p.str_of()));
        } else if t == "str" {
            // unowned str params: direct alloca+store, no null-init
            // (parse_array/object/value); the null pair is split-form only
            FN_S.with(|y| y.borrow_mut().push(p.str_of()));
            FN_PARAMS.with(|f| f.borrow_mut()
                .push((p.str_of(), t.clone())));
            container_pairs.push_str(&format!(
                "  %\"{}\" = alloca i8*\n  store i8* %\".{}\", i8** %\"{}\"\n",
                p.str_of(), i + 1, p.str_of()));
        } else {
            FN_PARAMS.with(|f| f.borrow_mut()
                .push((p.str_of(), t.clone())));
            if let Some(cls) = t.strip_prefix("inst:") {
                FN_TY.with(|y| y.borrow_mut()
                    .push((p.str_of(), cls.to_string())));
                // instance params: i8* alloca+store pairs (calc evidence)
                container_pairs.push_str(&format!(
                    "  %\"{}\" = alloca i8*\n  store i8* %\".{}\", i8** %\"{}\"\n",
                    p.str_of(), i + 1, p.str_of()));
                continue;
            }
            if t == "float" { FN_F.with(|f| f.borrow_mut().push(p.str_of())); }
            else { FN_I.with(|f| f.borrow_mut().push(p.str_of())); }
        }
    }
    // param stores forward at body start (silent slots); container
    // stores live in the splice but STILL consume their slot
    for (i, (p, t)) in params.iter().zip(atys.iter()).enumerate() {
        if SPLIT_FORM.with(|x| *x.borrow_mut()) { break; }
        // str pairs consume one splice slot (direct store); scalars one
        if t == "str" { b.silent(); continue; }
        b.silent();
        if t.starts_with("list:") || t.starts_with("inst:") { continue; }
        let ll = arg_ll(t);
        b.line(format!("  store {} %\".{}\", {}* %\"{}\"",
            ll, i + 1, ll, p.str_of()));
    }
    } else {
        // split form: params REVERSED (str: alloca+null+store inline;
        // containers: bare alloca), container stores deferred forward
        let mut deferred: Vec<String> = Vec::new();
        for (i, (p, t)) in params.iter().zip(atys.iter()).enumerate().rev() {
            if t == "str" {
                FN_S.with(|y| y.borrow_mut().push(p.str_of()));
                container_pairs.push_str(&format!(
                    "  %\"{}\" = alloca i8*\n  store i8* null, i8** %\"{}\"\n  store i8* %\".{}\", i8** %\"{}\"\n",
                    p.str_of(), p.str_of(), i + 1, p.str_of()));
                b.silent(); b.silent();
            } else if t.starts_with("inst:") {
                FN_TY.with(|y| y.borrow_mut().push(
                    (p.str_of(), t.strip_prefix("inst:").unwrap_or("").to_string())));
                container_pairs.push_str(&format!(
                    "  %\"{}\" = alloca i8*\n  store i8* %\".{}\", i8** %\"{}\"\n",
                    p.str_of(), i + 1, p.str_of()));
                b.silent();
            } else if t.starts_with("list:") {
                FN_L.with(|f| f.borrow_mut().push(
                    (p.str_of(), t.split(':').nth(1).unwrap_or("int").to_string())));
                container_pairs.push_str(&format!(
                    "  %\"{}\" = alloca i8*\n", p.str_of()));
                deferred.push(format!(
                    "  store i8* %\".{}\", i8** %\"{}\"",
                    i + 1, p.str_of()));
                b.silent();
            } else {
                container_pairs.push_str(&format!(
                    "  %\"{}\" = alloca {}\n", p.str_of(), arg_ll(t)));
                deferred.push(format!(
                    "  store {} %\".{}\", {}* %\"{}\"",
                    arg_ll(t), i + 1, arg_ll(t), p.str_of()));
                b.silent();
            }
        }
        for d in deferred {
            container_pairs.push_str(&d);
            container_pairs.push('\n');
        }
    }

    let mut loops: Vec<String> = Vec::new();
    let ended = conv_block(&mut b, &body, &mut loops, sc);
    if !ended {
        // implicit returns: typed null/zero defaults (calc: ret i8* null)
        b.silent();
        match rty.as_str() {
            "float" => b.line(format!(
                "  ret double {}", double_bits(0.0))),
            t if t.starts_with("inst:") || t == "str"
                || t.starts_with("list:") => b.line("  ret i8* null".into()),
            "none" | "pyobj" =>
                b.line("  ret {i32, i8*}* null".into()),
            _ => b.line("  ret i64 0".into()),
        }
    }
    IN_FN.with(|v| *v.borrow_mut() = false);

    // allocas: LOCALS reversed first, then PARAMS reversed (spectral)
    let mut alloca_lines = String::new();
    let alloca_ty = |t: &str| match t {
        "bool" => "i1",
        "view" => "{i64, i64, i8*, i64}",
        "pyobj" => "{i32, i8*}*",
        "list" | "str" | "inst" | "i8*" => "i8*",
        "i8*" => "i8*",
        "float" => "double",
        t if t.starts_with("list:") || t.starts_with("inst:")
            || t == "str" => "i8*",
        _ => "i64",
    };
    FN_ALLOCAS.with(|f| {
        for (nm, ty) in f.borrow().iter().rev() {
            alloca_lines.push_str(&format!("  %\"{}\" = alloca {}\n",
                nm, alloca_ty(ty)));
            if ty == "str" {
                alloca_lines.push_str(&format!(
                    "  store i8* null, i8** %\"{}\"\n", nm));
            }
        }
    });
    FN_PARAMS.with(|f| {
        for (nm, ty) in f.borrow().iter().rev() {
            if ty.starts_with("inst:") || ty == "str"
                || ty.starts_with("list:") { continue; }
            alloca_lines.push_str(&format!("  %\"{}\" = alloca {}\n",
                nm, alloca_ty(ty)));
        }
    });
    alloca_lines.push_str(&container_pairs);
    let mut out = b.render(&header);
    if let Some(epos) = out.find("entry:\n") {
        out.insert_str(epos + "entry:\n".len(), &alloca_lines);
    } else {
        out.push_str(&alloca_lines);
    }
    out
}

#[derive(Clone)]
enum Typed { I64(String), F64(String), Str(String), PStr(String),
             Inst(String), Pyo(String) } // Pyo = boxed {i32, i8*}* value

fn eval_expr(b: &mut FnB, e: &Val, slot_i: &dyn Fn(&str) -> String,
             slot_f: &dyn Fn(&str) -> String, sc: &mut usize,
             fslots: &[String]) -> Typed {
    // json_* builtins over the tagged-union Json representation
    // (jsonparse_json). Mirrors the eval_mod dispatch so that expr_i64
    // (aug-assign rhs, subscript indices) also reaches these builtins.
    if e.head() == "call" && e.get(1).head() == "name" {
        let fname = e.get(1).get(1).str_of();
        let jargs = e.get(2).items();
        if jargs.len() == 1 && fname.starts_with("json_") {
            let av = eval_expr(b, &jargs[0], slot_i, slot_f, sc, fslots);
            let jv = match av {
                Typed::Inst(r) | Typed::Str(r) => r,
                Typed::I64(r) => r,
                _ => bail("json arg"),
            };
            match fname.as_str() {
                "json_tag" => {
                    let t = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i32 @\"tagged_tag\"(i8* {})", t, jv));
                    let sx = b.nx();
                    b.line(format!(
                        "  %\"{}\" = sext i32 %\"{}\" to i64", sx, t));
                    return Typed::I64(format!("%\"{}\"", sx));
                }
                "json_int" => {
                    let c = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i64 @\"json_unwrap_int\"(i8* {})", c, jv));
                    return Typed::I64(format!("%\"{}\"", c));
                }
                "json_str" => {
                    let bw = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i8* @\"json_unwrap_str\"(i8* {})", bw, jv));
                    let cp = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i8* @\"rawstr_copy\"(i8* %\"{}\")", cp, bw));
                    return Typed::Str(format!("%\"{}\"", cp));
                }
                "json_list" | "json_dict" => {
                    let f = if fname == "json_list" { "json_unwrap_list" }
                            else { "json_unwrap_dict" };
                    let c = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i8* @\"{}\"(i8* {})", c, f, jv));
                    return Typed::Inst(format!("%\"{}\"", c));
                }
                "json_free" => {
                    b.silent();
                    b.line(format!(
                        "  call void @\"tagged_free\"(i8* {}, i32 4, i32 5, i32 6)", jv));
                    return Typed::I64("0".into());
                }
                _ => {}
            }
        }
    }
    if e.head() == "call" && e.get(1).head() == "name"
        && e.get(1).get(1).str_of() == "input" {
        let c = b.nx();
        b.line(format!(
            "  %\"{}\" = call {{i32, i8*}}* @\"pyobj_input\"()", c));
        let rr = b.nx();
        b.line(format!(
            "  %\"{}\" = call i8* @\"pystr_to_rawstr\"({{i32, i8*}}* %\"{}\")",
            rr, c));
        return Typed::Str(format!("%\"{}\"", rr));
    }
    if e.head() == "call" && e.get(1).head() == "name"
        && e.get(1).get(1).str_of() == "int" {
        // int(float): fptosi
        let ia = e.get(2).items();
        if ia.len() != 1 { bail("int arity"); }
        let v = eval_expr(b, &ia[0], slot_i, slot_f, sc, fslots);
        let r = to_f64(b, v);
        let c = b.nx();
        b.line(format!(
            "  %\"{}\" = fptosi double {} to i64", c, r));
        return Typed::I64(format!("%\"{}\"", c));
    }
    if e.head() == "call" && e.get(1).head() == "name"
        && e.get(1).get(1).str_of() == "float" {
        // float(str): copy -> to_cstr -> inline fend alloca -> strtod
        // -> validation panic pair -> free (calc evidence)
        let ia = e.get(2).items();
        if ia.len() != 1 { bail("float arity"); }
        let v = eval_expr(b, &ia[0], slot_i, slot_f, sc, fslots);
        let r = match v {
            Typed::Str(r) | Typed::Inst(r) => r,
            Typed::PStr(_) => to_raw(b, v, sc),
            _ => bail("float arg type"),
        };
        let cp = b.nx();
        b.line(format!(
            "  %\"{}\" = call i8* @\"rawstr_copy\"(i8* {})", cp, r));
        let cs = b.nx();
        b.line(format!(
            "  %\"{}\" = call i8* @\"rawstr_to_cstr\"(i8* %\"{}\")", cs, cp));
        let fn_ = b.uniq_label("fend");
        b.reg_names.push(fn_.clone());
        b.line(format!("  %\"{}\" = alloca i8*", fn_));
        let sd = b.nx();
        b.line(format!(
            "  %\"{}\" = call double @\"strtod\"(i8* %\"{}\", i8** %\"{}\")",
            sd, cs, fn_));
        let ld = b.nx();
        b.line(format!(
            "  %\"{}\" = load i8*, i8** %\"{}\"", ld, fn_));
        let ne = b.nx();
        b.line(format!(
            "  %\"{}\" = icmp ne i8* %\"{}\", %\"{}\"", ne, ld, cs));
        let xr = b.nx();
        b.line(format!(
            "  %\"{}\" = xor i1 %\"{}\", -1", xr, ne));
        b.silent();
        let suffix = b.panic_suffix();
        b.line(format!(
            "  br i1 %\"{}\", label %\"panic_bad{}\", label %\"panic_ok{}\"",
            xr, suffix.clone(), suffix));
        let bad = b.add_block(&format!("panic_bad{}", suffix));
        b.emit_panic_body(bad,
            "ValueError: invalid literal for float()", sc);
        let ok = b.add_block(&format!("panic_ok{}", suffix));
        b.pos(ok);
        b.silent();
        b.line(format!(
            "  call void @\"free\"(i8* %\"{}\")", cs));
        return Typed::F64(format!("%\"{}\"", sd));
    }
    if e.head() == "call" && e.get(1).head() == "name"
        && e.get(1).get(1).str_of() == "str" {
        // str(int) in expression position: create_int + conv
        let ia = e.get(2).items();
        if ia.len() != 1 { bail("str arity"); }
        let v = eval_expr(b, &ia[0], slot_i, slot_f, sc, fslots);
        let Typed::I64(r) = v else { bail("str arg type") };
        let c = b.nx();
        b.line(format!(
            "  %\"{}\" = call {{i32, i8*}}* @\"create_int\"(i64 {})", c, r));
        let cv = b.nx();
        b.line(format!(
            "  %\"{}\" = call {{i32, i8*}}* @\"pyobj_str_conv\"({{i32, i8*}}* %\"{}\")",
            cv, c));
        return Typed::PStr(format!("%\"{}\"", cv));
    }
    if e.head() == "const" && matches!(e.get(1), Val::Str(_)) {
        // str constant in expression position -> pystr create_str chain
        let text = e.get(1).str_of();
        let gname = add_str(sc, &text);
        let blen = text.chars().count();
        let g = b.nx();
        b.line(format!(
            "  %\"{}\" = getelementptr [{} x i8], [{} x i8]* @\"{}\", i32 0, i32 0",
            g, blen + 1, blen + 1, gname));
        let c = b.nx();
        b.line(format!(
            "  %\"{}\" = call {{i32, i8*}}* @\"create_str\"(i8* %\"{}\", i32 {})",
            c, g, blen));
        return Typed::PStr(format!("%\"{}\"", c));
    }
    match e.head() {
        "const" => match &e.items()[1] {
            Val::Int(v) => Typed::I64(v.to_string()),
            Val::Float(v) => Typed::F64(double_bits(*v)),
            Val::Null => Typed::Inst("null".into()),
            _ => bail("const type"),
        },
        "name" => {
            let n = e.get(1).str_of();
            let l = b.nx();
            let _ = (slot_i, slot_f);
            if is_local_s(&n) {
                b.line(format!("  %\"{}\" = load i8*, i8** %\"{}\"", l, n));
                return Typed::Str(format!("%\"{}\"", l));
            }
            if FN_L.with(|t| t.borrow().iter().any(|(k, _)| k == &n)) {
                b.line(format!("  %\"{}\" = load i8*, i8** %\"{}\"", l, n));
                return Typed::Inst(format!("%\"{}\"", l));
            }
            if FN_D.with(|t| t.borrow().iter().any(|k| k == &n)) {
                b.line(format!("  %\"{}\" = load i8*, i8** %\"{}\"", l, n));
                return Typed::Inst(format!("%\"{}\"", l));
            }
            if FN_PY.with(|t| t.borrow().iter().any(|x| x == &n)) {
                b.line(format!(
                    "  %\"{}\" = load {{i32, i8*}}*, {{i32, i8*}}** %\"{}\"",
                    l, n));
                return Typed::Pyo(format!("%\"{}\"", l));
            }
            if JSON_SLOTS.with(|t| t.borrow().iter().any(|x| x == &n)) {
                b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, n));
                return Typed::Inst(format!("%\"{}\"", l));
            }
            if fn_ty_of(&n).is_some() {
                if n == "self" || inst_stor(&n).is_none() {
                    b.line(format!("  %\"{}\" = load i8*, i8** %\"{}\"",
                        l, n));
                    return Typed::Inst(format!("%\"{}\"", l));
                }
                match inst_stor(&n).as_deref() {
                    Some("i8*") => {
                        b.line(format!(
                            "  %\"{}\" = load i8*, i8** %\"{}\"", l, n));
                        return Typed::Inst(format!("%\"{}\"", l));
                    }
                    _ => {
                        b.line(format!(
                            "  %\"{}\" = load i64, i64* %\"{}\"", l, n));
                        return Typed::I64(format!("%\"{}\"", l));
                    }
                }
            }
            if is_local_f(&n) || fslots.iter().any(|f| f == &n) {
                b.line(format!("  %\"{}\" = load double, double* {}",
                    l, if is_local_f(&n) { format!("%\"{}\"", n) }
                       else { format!("@\"{}\"", n) }));
                return Typed::F64(format!("%\"{}\"", l));
            }
            if is_local_i(&n) {
                b.line(format!("  %\"{}\" = load i64, i64* %\"{}\"", l, n));
                return Typed::I64(format!("%\"{}\"", l));
            }
            if STR_SLOTS.with(|t| t.borrow().iter().any(|f| f == &n)) {
                b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, n));
                return Typed::Str(format!("%\"{}\"", l));
            }
            if PY_SLOTS.with(|t| t.borrow().iter().any(|f| f == &n)) {
                b.line(format!(
                    "  %\"{}\" = load {{i32, i8*}}*, {{i32, i8*}}** @\"{}\"",
                    l, n));
                return Typed::Pyo(format!("%\"{}\"", l));
            }
            b.line(format!("  %\"{}\" = load i64, i64* @\"{}\"", l, n));
            Typed::I64(format!("%\"{}\"", l))
        }
        "-" if e.items().len() == 2 => {
            // unary minus: constants fold in the constant domain
            if e.get(1).head() == "const" {
                match &e.get(1).items()[1] {
                    Val::Float(v) =>
                        return Typed::F64(double_bits(-*v)),
                    Val::Int(v) => return Typed::I64((-v).to_string()),
                    _ => bail("unary minus const"),
                }
            }
            // names/exprs: multiply by -1.0 (fmul, not fneg)
            let v = eval_expr(b, &e.get(1), slot_i, slot_f, sc, fslots);
            match v {
                Typed::F64(r) => {
                    let m = b.nx();
                    b.line(format!(
                        "  %\"{}\" = fmul double {}, 0xbff0000000000000",
                        m, r));
                    Typed::F64(format!("%\"{}\"", m))
                }
                Typed::I64(_) => bail("unary minus int"),
                Typed::Str(_) | Typed::PStr(_) | Typed::Pyo(_) =>
                    bail("unary minus non-num"),
                Typed::Inst(_) => bail("unary minus inst"),
            }
        }
        "**" => {
            let lt = eval_expr(b, &e.get(1), slot_i, slot_f, sc, fslots);
            let l = to_f64(b, lt);
            match &e.get(2).items()[1] {
                Val::Float(v) if *v == 0.5 => {
                    let c = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call double @\"llvm.sqrt.f64\"(double {})",
                        c, l));
                    Typed::F64(format!("%\"{}\"", c))
                }
                _ => bail("pow exponent"),
            }
        }
        "attribute" if e.get(1).head() == "name" => {
            // enum value Tok.NUM or instance field self.toks / node.kind
            let base = e.get(1).get(1).str_of();
            let fld = e.get(2).str_of();
            if let Some(cls) = fn_ty_of(&base) {
                let fields = class_fields(&cls)
                    .unwrap_or_else(|| bail("class fields"));
                let (off, fty) = fields.iter().position(|(f, _)| f == &fld)
                    .map(|i| ((i * 8) as i64, fields[i].1.clone()))
                    .unwrap_or_else(|| bail("field"));
                // self/instance params: i8* pair; locals by storage
                let slot = if fn_ty_of(&base).is_some() {
                    format!("%\"{}\"", base)
                } else { format!("@\"{}\"", base) };
                let lv = if base == "self" || inst_stor(&base).is_none()
                    || inst_stor(&base).as_deref() == Some("i8*") {
                    let l = b.nx();
                    b.line(format!("  %\"{}\" = load i8*, i8** {}",
                        l, slot));
                    format!("%\"{}\"", l)
                } else {
                    let l = b.nx();
                    b.line(format!("  %\"{}\" = load i64, i64* {}",
                        l, slot));
                    let pt = b.nx();
                    b.line(format!(
                        "  %\"{}\" = inttoptr i64 %\"{}\" to i8*",
                        pt, l));
                    format!("%\"{}\"", pt)
                };
                let gp = b.nx();
                b.line(format!("  %\"{}\" = getelementptr i8, i8* {}, i64 {}",
                    gp, lv, off));
                match fty.as_str() {
                    t if is_enum(t) || t == "int" => {
                        let bc = b.nx();
                        b.line(format!(
                            "  %\"{}\" = bitcast i8* %\"{}\" to i64*", bc, gp));
                        let ld = b.nx();
                        b.line(format!(
                            "  %\"{}\" = load i64, i64* %\"{}\"", ld, bc));
                        Typed::I64(format!("%\"{}\"", ld))
                    }
                    "float" => {
                        let bc = b.nx();
                        b.line(format!(
                            "  %\"{}\" = bitcast i8* %\"{}\" to double*", bc, gp));
                        let ld = b.nx();
                        b.line(format!(
                            "  %\"{}\" = load double, double* %\"{}\"", ld, bc));
                        Typed::F64(format!("%\"{}\"", ld))
                    }
                    "int" => {
                        let bc = b.nx();
                        b.line(format!(
                            "  %\"{}\" = bitcast i8* %\"{}\" to i64*", bc, gp));
                        let ld = b.nx();
                        b.line(format!(
                            "  %\"{}\" = load i64, i64* %\"{}\"", ld, bc));
                        Typed::I64(format!("%\"{}\"", ld))
                    }
                    _ => { // str / instance fields load as i8*
                        let bc = b.nx();
                        b.line(format!(
                            "  %\"{}\" = bitcast i8* %\"{}\" to i8**", bc, gp));
                        let ld = b.nx();
                        b.line(format!(
                            "  %\"{}\" = load i8*, i8** %\"{}\"", ld, bc));
                        Typed::Inst(format!("%\"{}\"", ld))
                    }
                }
            } else if is_enum(&base) {
                let k = enum_val(&base, &fld)
                    .unwrap_or_else(|| bail("enum variant"));
                Typed::I64(k.to_string())
            } else { bail("attribute base") }
        }
        "subscript" if e.get(1).head() == "attribute" => {
            // self.toks[i]: field-resolved list read
            let base = e.get(1);
            let bn = base.get(1).get(1).str_of();
            let cls = fn_ty_of(&bn)
                .unwrap_or_else(|| bail("attr subscript base"));
            let fields = class_fields(&cls)
                .unwrap_or_else(|| bail("class fields"));
            let fld = base.get(2).str_of();
            let fty = fields.iter().find(|(f, _)| f == &fld)
                .map(|(_, t)| t.clone())
                .unwrap_or_else(|| bail("field"));
            let elty = fty.strip_prefix("list:")
                .unwrap_or_else(|| bail("not a list field"))
                .to_string();
            let bv = eval_expr(b, &base, slot_i, slot_f, sc, fslots);
            let or_ = match bv {
                Typed::Inst(r) => r,
                _ => bail("attr list ref"),
            };
            let kr = eval_expr(b, &e.get(2), slot_i, slot_f, sc, fslots);
            let Typed::I64(k) = kr else { bail("attr list key") };
            let r = b.list_get(&or_, &k, sc, &elty);
            if elty == "float" { return Typed::F64(r); }
            Typed::I64(r)
        }
        "subscript" => {
            if e.get(1).head() != "name" { bail("subscript base"); }
            let n = e.get(1).get(1).str_of();
            let objref = if DCT_SLOTS.with(|t| t.borrow().iter().any(|f| f == &n)) {
                // dict read: key type dispatch (int: rawdict_get;
                // str: concat chain to raw, rawdict_str_get)
                let l = b.nx();
                b.line(format!("  %\"{}\" = load i8*, i8** {}", l, dct_slot(&n)));
                if dct_key_ty(&n) == "str" {
                    // const str key: the checked key_str_ok/err + str_view
                    // unpack shape, then rawdict_str_get (o["id"] evidence)
                    if e.get(2).head() == "const"
                        && matches!(e.get(2).get(1), Val::Str(_)) {
                        let text = e.get(2).get(1).str_of();
                        let r = emit_const_key_direct(b,
                            &format!("%\"{}\"", l), &text, sc);
                        return Typed::I64(r);
                    }
                    let kr = if let Some((bname, sl)) = as_slice_sub(&e.get(2)) {
                        let bn = if bname.is_empty() { n.clone() } else { bname };
                        emit_slice_view(b, &bn, &sl, sc)
                    } else {
                        let kv = eval_expr(b, &e.get(2), slot_i, slot_f, sc, fslots);
                        to_raw(b, kv, sc)
                    };
                    let c = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i64 @\"rawdict_str_get\"(i8* %\"{}\", i8* {})",
                        c, l, kr));
                    return Typed::I64(format!("%\"{}\"", c));
                }
                let k = eval_expr(b, &e.get(2), slot_i, slot_f, sc, fslots);
                let Typed::I64(kr) = k else { bail("dict key type") };
                let c = b.nx();
                b.line(format!(
                        "  %\"{}\" = call i64 @\"rawdict_get\"(i8* %\"{}\", i64 {})", c, l, kr));
                    return Typed::I64(format!("%\"{}\"", c));
            } else if LST_SLOTS.with(|t| t.borrow().iter().any(|f| f == &n))
                || FN_L.with(|t| t.borrow().iter().any(|(k, _)| k == &n)) {
                // list read: load obj, key, bounds-checked get_ok
                let l = b.nx();
                b.line(format!("  %\"{}\" = load i8*, i8** {}",
                    l, lst_slot(&n)));
                format!("%\"{}\"", l)
            } else if e.get(2).head() == "slice"
                && (STR_SLOTS.with(|t| t.borrow().iter().any(|f| f == &n))
                    || is_local_s(&n)) {
                // str slice: (dead len read) + slice + copy (calc)
                let l = b.nx();
                let slot0 = if is_local_s(&n) { format!("%\"{}\"", n) }
                           else { format!("@\"{}\"", n) };
                b.line(format!("  %\"{}\" = load i8*, i8** {}",
                    l, slot0));
                let bc = b.nx();
                b.line(format!(
                    "  %\"{}\" = bitcast i8* %\"{}\" to {{i64, i64, i8*, i64}}*",
                    bc, l));
                let g3 = b.nx();
                b.line(format!(
                    "  %\"{}\" = getelementptr {{i64, i64, i8*, i64}}, {{i64, i64, i8*, i64}}* %\"{}\", i32 0, i32 3",
                    g3, bc));
                let dl = b.nx();
                b.line(format!(
                    "  %\"{}\" = load i64, i64* %\"{}\"", dl, g3));
                let sv = eval_expr(b, &e.get(2).get(1), slot_i, slot_f, sc, fslots);
                let Typed::I64(sr) = sv else { bail("slice start") };
                let ev = eval_expr(b, &e.get(2).get(2), slot_i, slot_f, sc, fslots);
                let Typed::I64(er) = ev else { bail("slice end") };
                let sl = b.nx();
                b.line(format!(
                    "  %\"{}\" = call i8* @\"rawstr_slice\"(i8* %\"{}\", i64 {}, i64 {})",
                    sl, l, sr, er));
                if SLICE_NO_COPY.with(|c| *c.borrow()) {
                    return Typed::Str(format!("%\"{}\"", sl));
                }
                let cp = b.nx();
                b.line(format!(
                    "  %\"{}\" = call i8* @\"rawstr_copy\"(i8* %\"{}\")",
                    cp, sl));
                return Typed::Str(format!("%\"{}\"", cp));
            } else if is_py(&n) {
                // dynamic subscript: create_int / create_str key +
                // pyobj_subscript -> pyobj
                let l = b.nx();
                b.line(format!(
                    "  %\"{}\" = load {{i32, i8*}}*, {{i32, i8*}}** @\"{}\"",
                    l, n));
                if e.get(2).head() == "const"
                    && matches!(e.get(2).get(1), Val::Str(_)) {
                    let text = e.get(2).get(1).str_of();
                    let blen = text.chars().count();
                    let gname = add_str(sc, &text);
                    let g = b.nx();
                    b.line(format!(
                        "  %\"{}\" = getelementptr [{} x i8], [{} x i8]* @\"{}\", i32 0, i32 0",
                        g, blen + 1, blen + 1, gname));
                    let cs = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call {{i32, i8*}}* @\"create_str\"(i8* %\"{}\", i32 {})",
                        cs, g, blen));
                    let c2 = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call {{i32, i8*}}* @\"pyobj_subscript\"({{i32, i8*}}* %\"{}\", {{i32, i8*}}* %\"{}\")",
                        c2, l, cs));
                    return Typed::Pyo(format!("%\"{}\"", c2));
                }
                let kv = eval_expr(b, &e.get(2), slot_i, slot_f, sc, fslots);
                let Typed::I64(k) = kv else { bail("pyobj key type") };
                let ci = b.nx();
                b.line(format!(
                    "  %\"{}\" = call {{i32, i8*}}* @\"create_int\"(i64 {})",
                    ci, k));
                let c2 = b.nx();
                b.line(format!(
                    "  %\"{}\" = call {{i32, i8*}}* @\"pyobj_subscript\"({{i32, i8*}}* %\"{}\", {{i32, i8*}}* %\"{}\")",
                    c2, l, ci));
                return Typed::Pyo(format!("%\"{}\"", c2));
            } else if STR_SLOTS.with(|t| t.borrow().iter().any(|f| f == &n))
                || is_local_s(&n) {
                // str char read: cv machinery -> 1-char str
                let l = b.nx();
                let slot = if is_local_s(&n) { format!("%\"{}\"", n) }
                           else { format!("@\"{}\"", n) };
                b.line(format!("  %\"{}\" = load i8*, i8** {}", l, slot));
                let kr = eval_expr(b, &e.get(2), slot_i, slot_f, sc, fslots);
                let Typed::I64(k) = kr else { bail("str key type") };
                let r = b.str_char_at(&format!("%\"{}\"", l), &k, sc);
                return Typed::Str(r);
            } else { bail("subscript read type"); };
            let kr = eval_expr(b, &e.get(2), slot_i, slot_f, sc, fslots);
            let Typed::I64(k) = kr else { bail("list key type") };
            let elty = lst_elem_ty(&n);
            let r = b.list_get(&objref, &k, sc, &elty);
            if elty == "float" { Typed::F64(r) } else { Typed::I64(r) }
        }
        "call" => {
            // len() reached from expression position: route through
            // eval_mod's builtin dispatch (list/dict/str/pyobj shapes)
            if e.get(1).head() == "name"
                && e.get(1).get(1).str_of() == "len" {
                return eval_mod(b, e, fslots, sc);
            }
            // constructor: Class(args) -> inline malloc + field stores
            if e.get(1).head() == "name" && is_class(&e.get(1).get(1).str_of()) {
                let cls = e.get(1).get(1).str_of();
                if is_dyn_class(&cls) {
                    return emit_dyn_ctor(b, e, &cls, sc,
                        slot_i, slot_f, fslots);
                }
                let fields = class_fields(&cls)
                    .unwrap_or_else(|| bail("class fields"));
                let args = e.get(2).items();
                let c = b.nx();
                b.line(format!(
                    "  %\"{}\" = call i8* @\"malloc\"(i64 {})",
                    c, (fields.len() * 8) as i64));
                for (i, (_, fty)) in fields.iter().enumerate() {
                    let av = eval_expr(b, &args[i], slot_i, slot_f, sc, fslots);
                    // str fields: to_raw BEFORE the field gep (calc)
                    let av = match (&av, fty.as_str()) {
                        (Typed::PStr(_), _) if fty != "float" && fty != "int"
                            && !is_enum(fty) => {
                            let r = to_raw(b, av, sc);
                            Typed::Str(r)
                        }
                        _ => av,
                    };
                    let gp = b.nx();
                    b.line(format!(
                        "  %\"{}\" = getelementptr i8, i8* %\"{}\", i64 {}",
                        gp, c, (i * 8) as i64));
                    match (av, fty.as_str()) {
                        (Typed::I64(r), _) if is_enum(fty) || fty == "int" => {
                            let bc = b.nx();
                            b.line(format!(
                                "  %\"{}\" = bitcast i8* %\"{}\" to i64*", bc, gp));
                            b.silent();
                            b.line(format!("  store i64 {}, i64* %\"{}\"", r, bc));
                        }
                        (v, "float") => {
                            let r = to_f64(b, v);
                            let bc = b.nx();
                            b.line(format!(
                                "  %\"{}\" = bitcast i8* %\"{}\" to double*", bc, gp));
                            b.silent();
                            b.line(format!("  store double {}, double* %\"{}\"", r, bc));
                        }
                        (v, _) => { // str / instance / None -> i8* slot
                            let r = match v {
                                Typed::Inst(r) | Typed::Str(r) => r,
                                Typed::PStr(_) => to_raw(b, v, sc),
                                Typed::I64(ir) => {
                                    let pt = b.nx();
                                    b.line(format!(
                                        "  %\"{}\" = inttoptr i64 {} to i8*",
                                        pt, ir));
                                    format!("%\"{}\"", pt)
                                }
                                _ => bail("ctor field type"),
                            };
                            let bc = b.nx();
                            b.line(format!(
                                "  %\"{}\" = bitcast i8* %\"{}\" to i8**", bc, gp));
                            b.silent();
                            b.line(format!("  store i8* {}, i8** %\"{}\"", r, bc));
                        }
                    }
                }
                return Typed::Inst(format!("%\"{}\"", c));
            }
            // method call: obj.method(a) -> Class__method(obj, a)
            if e.get(1).head() == "attribute" {
                let base = e.get(1).get(1);
                let mname = e.get(1).get(2).str_of();
                if base.head() != "name" { bail("method base"); }
                let bn = base.get(1).str_of();
                let cls = fn_ty_of(&bn)
                    .unwrap_or_else(|| bail("method base type"));
                let target = format!("{}__{}", cls, mname);
                // method dispatch: double-load the base (calc evidence)
                let _bv = eval_expr(b, &base, slot_i, slot_f, sc, fslots);
                let is_ptr = bn == "self" || inst_stor(&bn).is_none()
                    || inst_stor(&bn).as_deref() == Some("i8*");
                let or_ = {
                    let lv = b.nx();
                    if is_ptr {
                        b.line(format!("  %\"{}\" = load i8*, i8** %\"{}\"",
                            lv, bn));
                    } else {
                        b.line(format!("  %\"{}\" = load i64, i64* %\"{}\"",
                            lv, bn));
                        let pt = b.nx();
                        b.line(format!(
                            "  %\"{}\" = inttoptr i64 %\"{}\" to i8*",
                            pt, lv));
                    }
                    format!("%\"{}\"", lv)
                };
                let sig = FN_SIGS.with(|m| m.borrow().iter()
                    .find(|(k, _, _)| k == &target).cloned());
                let (_, atys, rty) = match sig {
                    Some(t) => t,
                    None => (String::new(), vec!["int".to_string(); 99],
                             "int".to_string()),
                };
                let args = e.get(2).items();
                let mut parts = vec![format!("i8* {}", or_)];
                for (i, a) in args.iter().enumerate() {
                    let ty = atys.get(i + 1).map(|s| s.as_str()).unwrap_or("int");
                    if ty.starts_with("inst:") || ty == "str" {
                        let av = eval_expr(b, a, slot_i, slot_f, sc, fslots);
                        match av {
                            Typed::Inst(r) | Typed::Str(r) =>
                                parts.push(format!("i8* {}", r)),
                            Typed::PStr(_) => {
                                let r = to_raw(b, av, sc);
                                parts.push(format!("i8* {}", r));
                            }
                            _ => bail("method arg type"),
                        }
                        continue;
                    }
                    let av = eval_expr(b, a, slot_i, slot_f, sc, fslots);
                    match av {
                        Typed::I64(r) => parts.push(format!("i64 {}", r)),
                        v => { let r = to_f64(b, v);
                               parts.push(format!("double {}", r)); }
                    }
                }
                let c = b.nx();
                let rll = match rty.as_str() {
                    "float" => "double",
                    "none" | "pyobj" => "{i32, i8*}*",
                    t if t.starts_with("inst:") || t == "str" => "i8*",
                    _ => "i64",
                };
                b.line(format!("  %\"{}\" = call {} @\"{}\"({})",
                    c, rll, target, parts.join(", ")));
                if rty == "float" { return Typed::F64(format!("%\"{}\"", c)); }
                if rty.starts_with("inst:") || rty == "str" {
                    return Typed::Inst(format!("%\"{}\"", c));
                }
                if rty == "none" || rty == "pyobj" {
                    return Typed::Pyo(format!("%\"{}\"", c));
                }
                return Typed::I64(format!("%\"{}\"", c));
            }
            // user function call: eval args left to right, valued call;
            // arg/return types come from the collected signatures
            let fname = e.get(1).get(1).str_of();
            if e.get(1).head() != "name" { bail("call target"); }
            let sig = FN_SIGS.with(|m| m.borrow().iter()
                .find(|(k, _, _)| k == &fname).cloned());
            let (_, atys, rty) = match sig {
                Some(t) => t,
                None => (String::new(), vec!["int".to_string(); 99],
                         "int".to_string()),
            };
            let args = e.get(2).items();
            let mut parts = Vec::new();
            for (i, a) in args.iter().enumerate() {
                let ty = atys.get(i).map(|s| s.as_str()).unwrap_or("int");
                if ty.starts_with("list:") {
                    // container arg: name -> load slot; literal -> inline
                    // rawlist_new + element pushes (jsonparse [0] evidence)
                    if a.head() == "name" {
                        let nm = a.get(1).str_of();
                        let l = b.nx();
                        b.line(format!("  %\"{}\" = load i8*, i8** {}",
                            l, lst_slot(&nm)));
                        parts.push(format!("i8* %\"{}\"", l));
                        continue;
                    }
                    if a.head() == "list" {
                        let elems = a.items().get(1).cloned()
                            .unwrap_or(Val::Null);
                        if rty == "pyobj" || rty == "json" {
                            // pyobj/json-callee list literal arg: boxed domain
                            // create_list + create_int + list_append,
                            // then pylist_to_rawlist (main [0] evidence)
                            let c = b.nx();
                            b.line(format!(
                                "  %\"{}\" = call {{i32, i8*}}* @\"create_list\"()", c));
                            if let Val::List(vs) = &elems {
                                for el in vs.iter() {
                                    let ev = eval_expr(b, el, slot_i, slot_f,
                                        sc, fslots);
                                    let Typed::I64(r) = ev else {
                                        bail("py list lit elem") };
                                    let bi = b.nx();
                                    b.line(format!(
                                        "  %\"{}\" = call {{i32, i8*}}* @\"create_int\"(i64 {})",
                                        bi, r));
                                    let ap = b.nx();
                                    b.line(format!(
                                        "  %\"{}\" = call {{i32, i8*}}* @\"list_append\"({{i32, i8*}}* %\"{}\", {{i32, i8*}}* %\"{}\")",
                                        ap, c, bi));
                                }
                            }
                            let rl = b.nx();
                            b.line(format!(
                                "  %\"{}\" = call i8* @\"pylist_to_rawlist\"({{i32, i8*}}* %\"{}\")",
                                rl, c));
                            parts.push(format!("i8* %\"{}\"", rl));
                            continue;
                        }
                        let c = b.nx();
                        b.line(format!(
                            "  %\"{}\" = call i8* @\"rawlist_new\"(i64 8)", c));
                        if let Val::List(vs) = &elems {
                            for el in vs.iter() {
                                let ev = eval_expr(b, el, slot_i, slot_f,
                                    sc, fslots);
                                let Typed::I64(r) = ev else {
                                    bail("list lit elem") };
                                let pu = b.nx();
                                b.line(format!(
                                    "  %\"{}\" = call i64 @\"rawlist_push\"(i8* %\"{}\", i64 {})",
                                    pu, c, r));
                            }
                        }
                        parts.push(format!("i8* %\"{}\"", c));
                        continue;
                    }
                    bail("call list arg");
                }
                let av = eval_expr(b, a, slot_i, slot_f, sc, fslots);
                match (av, ty) {
                    (Typed::I64(r), "int") => parts.push(format!("i64 {}", r)),
                    (v, "float") => {
                        let r = to_f64(b, v);
                        parts.push(format!("double {}", r));
                    }
                    (v, t) if t == "str" || t.starts_with("inst:")
                        || t.starts_with("list:") => {
                        let r = match v {
                            Typed::Inst(r) | Typed::Str(r) => r,
                            Typed::PStr(_) => to_raw(b, v, sc),
                            Typed::I64(ir) => {
                                let pt = b.nx();
                                b.line(format!(
                                    "  %\"{}\" = inttoptr i64 {} to i8*",
                                    pt, ir));
                                format!("%\"{}\"", pt)
                            }
                            _ => bail("call arg type"),
                        };
                        parts.push(format!("i8* {}", r));
                    }
                    _ => { eprintln!("ucall fail f={} ty={}", fname, ty);
                        bail("call arg type") },
                }
            }
            let c = b.nx();
            let rll = match rty.as_str() {
                "float" => "double", "none" | "pyobj" => "{i32, i8*}*",
                t if t == "str" || t == "json" || t.starts_with("inst:")
                    || t.starts_with("list:") => "i8*",
                _ => "i64",
            };
            b.line(format!("  %\"{}\" = call {} @\"{}\"({})",
                c, rll, fname, parts.join(", ")));
            if rty == "float" { return Typed::F64(format!("%\"{}\"", c)); }
            if rty == "str" || rty == "json" || rty.starts_with("inst:")
                || rty.starts_with("list:") {
                return Typed::Inst(format!("%\"{}\"", c));
            }
            if rty == "none" || rty == "pyobj" {
                return Typed::Pyo(format!("%\"{}\"", c));
            }
            Typed::I64(format!("%\"{}\"", c))
        }
        "+" if (e.get(1).head() == "const"
                  && matches!(e.get(1).get(1), Val::Str(_)))
             || (e.get(2).head() == "const"
                  && matches!(e.get(2).get(1), Val::Str(_)))
             || e.get(2).head() == "call" && e.get(2).get(1).head() == "name"
                  && e.get(2).get(1).get(1).str_of() == "str" => {
            // str concat: eval both sides (pystr domain), to_rawstr each
            // in order, rawstr_concat (wordcount evidence)
            let _ = slot_f;
            let lt = eval_expr(b, &e.get(1),
                &|n: &str| format!("@\"{}\"", n),
                &|n: &str| format!("@\"{}\"", n), sc, fslots);
            let rt = eval_expr(b, &e.get(2),
                &|n: &str| format!("@\"{}\"", n),
                &|n: &str| format!("@\"{}\"", n), sc, fslots);
            let (lref, lpy) = pystr_of(b, &lt, sc);
            let (rref, rpy) = pystr_of(b, &rt, sc);
            if !lpy && !rpy { bail("both raw concat"); }
            let lr = if lpy { to_raw(b, lt, sc) } else { lref };
            let rr = if rpy { to_raw(b, rt, sc) } else { rref };
            let cc = b.nx();
            b.line(format!(
                "  %\"{}\" = call i8* @\"rawstr_concat\"(i8* {}, i8* {})",
                cc, lr, rr));
            Typed::Str(format!("%\"{}\"", cc))
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
                    // int / int is Python float division: INT zero check
                    // (icmp eq), then sitofp both, fdiv (spectral evidence)
                    b.zero_check(&r, sc);
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
        Typed::Str(_) | Typed::PStr(_) => bail("str where float expected"),
        Typed::Pyo(_) => bail("pyobj where float expected"),
        Typed::Inst(_) => bail("inst where float expected"),
    }
}

// str operand -> (pystr ref or raw ref); consts build create_str,
// str(int) builds create_int + pyobj_str_conv (wordcount evidence)
// force a str-typed value to a raw i8* ref (to_rawstr when pystr)
fn to_raw(b: &mut FnB, t: Typed, sc: &mut usize) -> String {
    let _ = sc;
    match t {
        Typed::Str(r) => r,
        Typed::PStr(r) => {
            let rr = b.nx();
            b.line(format!(
                "  %\"{}\" = call i8* @\"pystr_to_rawstr\"({{i32, i8*}}* {})",
                rr, r));
            format!("%\"{}\"", rr)
        }
        _ => bail("to_raw on non-str"),
    }
}

fn pystr_of(b: &mut FnB, t: &Typed, sc: &mut usize) -> (String, bool) {
    match t {
        Typed::PStr(r) => (r.clone(), true),      // pystr: needs to_rawstr
        Typed::Str(r) => (r.clone(), false),      // already raw
        Typed::I64(_) => {
            // str(x) folded earlier; bare int -> create_int + conv
            let _ = sc;
            bail("int in str expr")
        }
        _ => bail("str operand"),
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
                Typed::PStr(_) => {
                    // pystr-typed arg: to_rawstr, then the %.*s shape
                    let r0 = match &v_typed { Typed::PStr(r) => r.clone(),
                                             _ => unreachable!() };
                    let rr = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i8* @\"pystr_to_rawstr\"({{i32, i8*}}* {})",
                        rr, r0));
                    let bc = b.nx();
                    b.line(format!(
                        "  %\"{}\" = bitcast i8* %\"{}\" to {{i64, i64, i8*, i64}}*", bc, rr));
                    let gl = b.nx();
                    b.line(format!(
                        "  %\"{}\" = getelementptr {{i64, i64, i8*, i64}}, {{i64, i64, i8*, i64}}* %\"{}\", i32 0, i32 0",
                        gl, bc));
                    let len = b.nx();
                    b.line(format!(
                        "  %\"{}\" = load i64, i64* %\"{}\"", len, gl));
                    let gd = b.nx();
                    b.line(format!(
                        "  %\"{}\" = getelementptr {{i64, i64, i8*, i64}}, {{i64, i64, i8*, i64}}* %\"{}\", i32 0, i32 2",
                        gd, bc));
                    let data = b.nx();
                    b.line(format!(
                        "  %\"{}\" = load i8*, i8** %\"{}\"", data, gd));
                    let fmt = add_str(sc, "%.*s");
                    let fg = b.nx();
                    b.line(format!(
                        "  %\"{}\" = getelementptr [5 x i8], [5 x i8]* @\"{}\", i32 0, i32 0",
                        fg, fmt));
                    let pr = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i32 (i8*, ...) @\"printf\"(i8* %\"{}\", i64 %\"{}\", i8* %\"{}\")",
                        pr, fg, len, data));
                }
                Typed::Inst(_) => bail("print instance"),
                Typed::Pyo(_) => bail("print pyobj"),
                Typed::Str(r) => {
                    // str NAME arg: %.*s with (len field 0, data field 2)
                    let bc = b.nx();
                    b.line(format!(
                        "  %\"{}\" = bitcast i8* {} to {{i64, i64, i8*, i64}}*", bc, r));
                    let gl = b.nx();
                    b.line(format!(
                        "  %\"{}\" = getelementptr {{i64, i64, i8*, i64}}, {{i64, i64, i8*, i64}}* %\"{}\", i32 0, i32 0",
                        gl, bc));
                    let len = b.nx();
                    b.line(format!(
                        "  %\"{}\" = load i64, i64* %\"{}\"", len, gl));
                    let gd = b.nx();
                    b.line(format!(
                        "  %\"{}\" = getelementptr {{i64, i64, i8*, i64}}, {{i64, i64, i8*, i64}}* %\"{}\", i32 0, i32 2",
                        gd, bc));
                    let data = b.nx();
                    b.line(format!(
                        "  %\"{}\" = load i8*, i8** %\"{}\"", data, gd));
                    let fmt = add_str(sc, "%.*s");
                    let fg = b.nx();
                    b.line(format!(
                        "  %\"{}\" = getelementptr [5 x i8], [5 x i8]* @\"{}\", i32 0, i32 0",
                        fg, fmt));
                    let pr = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i32 (i8*, ...) @\"printf\"(i8* %\"{}\", i64 %\"{}\", i8* %\"{}\")",
                        pr, fg, len, data));
                }
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

// dna[s:e] as a dict key: rawstr_slice_parts + a temp str_view
// struct (alloca hoisted to the function's entry) + bitcast to i8*
// dna[s:e] arrives as subscript(dna, slice(...)): unwrap to (base, slice)
// const str key in d.get("K", def): create_str, TAG CHECK pair
// (key_str_ok/key_str_err), unpack the pystr payload into a str_view,
// rawdict_str_get_or(dict, view, def)
// ---- pyobj boxed layer (jsonparse blueprint) ----

// classify a return expression's static type for untyped-ret inference
fn infer_ret_of(e: &Val, binds: &[(String, String)]) -> String {
    match e.head() {
        "const" => match &e.items()[1] {
            Val::Int(_) => "int".into(),
            Val::Float(_) => "float".into(),
            Val::Str(_) => "str".into(),
            _ => "none".into(),
        },
        "name" => binds.iter().rev()
            .find(|(k, _)| k == &e.get(1).str_of())
            .map(|(_, t)| t.clone()).unwrap_or_else(|| "none".into()),
        "call" => {
            if e.get(1).head() == "name"
                && is_class(&e.get(1).get(1).str_of()) {
                if is_dyn_class(&e.get(1).get(1).str_of()) { "pyobj".into() }
                else { "inst".into() }
            } else if e.get(1).head() == "name"
                && PY_RETS.with(|r| r.borrow().iter()
                    .any(|x| *x == e.get(1).get(1).str_of())) {
                "pyobj".into()
            } else { "int".into() }
        }
        _ => "int".into(),
    }
}

// pre-scan a function body for binding declarations + returns
fn infer_ret(body: &[Val], params: &[Val],
             annos: &[Val]) -> String {
    let mut binds: Vec<(String, String)> = Vec::new();
    for (p, a) in params.iter().zip(annos.iter()) {
        let t = if a.head() == "subscript" { "list".to_string() }
                else { a.get(1).str_of() };
        binds.push((p.str_of(), t));
    }
    fn scan(stmts: &[Val], binds: &mut Vec<(String, String)>) -> String {
        for st in stmts.iter() {
            if !matches!(st, Val::List(_)) { continue; }
            match st.head() {
                "ann_assign" => binds.push((
                    st.get(1).str_of(), st.get(3).get(1).str_of())),
                "assign" => {
                    let rh = st.get(2);
                    let t = match rh.head() {
                        "list" => Some("pyobj".to_string()),
                        "dict" => Some("pyobj".to_string()),
                        _ => None,
                    };
                    if let Some(t) = t {
                        binds.push((st.get(1).str_of(), t))
                    }
                }
                "return" => {
                    return infer_ret_of(&st.get(1), binds)
                }
                "if" => {
                    let r = scan(&st.get(2).items(), binds);
                    if r != "none" { return r; }
                    let r2 = scan(&st.get(3).items(), binds);
                    if r2 != "none" { return r2; }
                }
                "while" => {
                    let r = scan(&st.get(2).items(), binds);
                    if r != "none" { return r; }
                }
                _ => {}
            }
        }
        "none".to_string()
    }
    scan(body, &mut binds)
}

// dynamic-class ctor: malloc + typed field stores + make_instance(CID)
fn emit_dyn_ctor(b: &mut FnB, e: &Val, cls: &str, sc: &mut usize,
                 slot_i: &dyn Fn(&str) -> String,
                 slot_f: &dyn Fn(&str) -> String,
                 fslots: &[String]) -> Typed {
    let fields = class_fields(cls)
        .unwrap_or_else(|| bail("class fields"));
    let args = e.get(2).items();
    let c = b.nx();
    b.line(format!(
        "  %\"{}\" = call i8* @\"malloc\"(i64 {})",
        c, (fields.len() * 8) as i64));
    for (i, (_, fty)) in fields.iter().enumerate() {
        let av = eval_expr(b, &args[i], slot_i, slot_f, sc, fslots);
        // per-field conversion lands BETWEEN the arg eval and the gep
        // (JStr copy / float to_f64 / raw-able to_raw evidence)
        enum Fv { Py(String), Str(String), Raw(String), F64(String),
                  I64(String) }
        let v = match (av, fty.as_str()) {
            (Typed::Pyo(r), _) => Fv::Py(r),
            (Typed::Str(r), "str") | (Typed::Inst(r), "str") => {
                // str fields store a COPY (JStr evidence)
                let cp = b.nx();
                b.line(format!(
                    "  %\"{}\" = call i8* @\"rawstr_copy\"(i8* {})", cp, r));
                Fv::Str(format!("%\"{}\"", cp))
            }
            (v, "float") => Fv::F64(to_f64(b, v)),
            (Typed::I64(r), _) => Fv::I64(r),
            (v, _) => Fv::Raw(to_raw(b, v, sc)),
        };
        let gp = b.nx();
        b.line(format!(
            "  %\"{}\" = getelementptr i8, i8* %\"{}\", i64 {}",
            gp, c, (i * 8) as i64));
        match v {
            Fv::Py(r) => {
                let bc = b.nx();
                b.line(format!(
                    "  %\"{}\" = bitcast i8* %\"{}\" to {{i32, i8*}}**",
                    bc, gp));
                b.silent();
                b.line(format!(
                    "  store {{i32, i8*}}* {}, {{i32, i8*}}** %\"{}\"",
                    r, bc));
            }
            Fv::Str(r) | Fv::Raw(r) => {
                let bc = b.nx();
                b.line(format!(
                    "  %\"{}\" = bitcast i8* %\"{}\" to i8**", bc, gp));
                b.silent();
                b.line(format!("  store i8* {}, i8** %\"{}\"", r, bc));
            }
            Fv::F64(r) => {
                let bc = b.nx();
                b.line(format!(
                    "  %\"{}\" = bitcast i8* %\"{}\" to double*", bc, gp));
                b.silent();
                b.line(format!(
                    "  store double {}, double* %\"{}\"", r, bc));
            }
            Fv::I64(r) => {
                let bc = b.nx();
                b.line(format!(
                    "  %\"{}\" = bitcast i8* %\"{}\" to i64*", bc, gp));
                b.silent();
                b.line(format!("  store i64 {}, i64* %\"{}\"", r, bc));
            }
        }
    }
    let m = b.nx();
    b.line(format!(
        "  %\"{}\" = call {{i32, i8*}}* @\"pyobj_make_instance\"(i64 {}, i8* %\"{}\")",
        m, class_cid(cls), c));
    Typed::Pyo(format!("%\"{}\"", m))
}

fn emit_const_key_get(b: &mut FnB, dl: &str, text: &str, def: i64,
                      sc: &mut usize) -> String {
    emit_const_key_get_mode(b, dl, text, Some(def), sc)
}

// direct subscript (o["id"]): rawdict_str_get, no default; the key
// type-check + str_view unpack shape is shared with d.get(key, def)
fn emit_const_key_direct(b: &mut FnB, dl: &str, text: &str,
                         sc: &mut usize) -> String {
    emit_const_key_get_mode(b, dl, text, None, sc)
}

fn emit_const_key_get_mode(b: &mut FnB, dl: &str, text: &str,
                           def: Option<i64>, sc: &mut usize) -> String {
    let gname = add_str(sc, text);
    let blen = text.chars().count();
    let g = b.nx();
    b.line(format!(
        "  %\"{}\" = getelementptr [{} x i8], [{} x i8]* @\"{}\", i32 0, i32 0",
        g, blen + 1, blen + 1, gname));
    let cs = b.nx();
    b.line(format!(
        "  %\"{}\" = call {{i32, i8*}}* @\"create_str\"(i8* %\"{}\", i32 {})",
        cs, g, blen));
    let gp0 = b.nx();
    b.line(format!(
        "  %\"{}\" = getelementptr {{i32, i8*}}, {{i32, i8*}}* %\"{}\", i32 0, i32 0",
        gp0, cs));
    let tg = b.nx();
    b.line(format!(
        "  %\"{}\" = load i32, i32* %\"{}\"", tg, gp0));
    let eq = b.nx();
    b.line(format!(
        "  %\"{}\" = icmp eq i32 %\"{}\", 2", eq, tg));
    let ok_lbl = b.uniq_label("key_str_ok");
    let err_lbl = b.uniq_label("key_str_err");
    b.silent();
    b.line(format!(
        "  br i1 %\"{}\", label %\"{}\", label %\"{}\"",
        eq, ok_lbl, err_lbl));
    let ob = b.add_block(&ok_lbl);
    b.pos(ob);
    let eb = b.add_block(&err_lbl);
    b.emit_panic_body(eb, "TypeError: expected str key", sc);
    b.pos(ob);
    // unpack: field1 -> payload {i32,i8*}*, its field1 = chars, field0 = len
    let gp1 = b.nx();
    b.line(format!(
        "  %\"{}\" = getelementptr {{i32, i8*}}, {{i32, i8*}}* %\"{}\", i32 0, i32 1",
        gp1, cs));
    let pay = b.nx();
    b.line(format!(
        "  %\"{}\" = load i8*, i8** %\"{}\"", pay, gp1));
    let pbc = b.nx();
    b.line(format!(
        "  %\"{}\" = bitcast i8* %\"{}\" to {{i32, i8*}}*", pbc, pay));
    let pc1 = b.nx();
    b.line(format!(
        "  %\"{}\" = getelementptr {{i32, i8*}}, {{i32, i8*}}* %\"{}\", i32 0, i32 1",
        pc1, pbc));
    let chars = b.nx();
    b.line(format!(
        "  %\"{}\" = load i8*, i8** %\"{}\"", chars, pc1));
    let pc0 = b.nx();
    b.line(format!(
        "  %\"{}\" = getelementptr {{i32, i8*}}, {{i32, i8*}}* %\"{}\", i32 0, i32 0",
        pc0, pbc));
    let len32 = b.nx();
    b.line(format!(
        "  %\"{}\" = load i32, i32* %\"{}\"", len32, pc0));
    let sx = b.nx();
    b.line(format!(
        "  %\"{}\" = sext i32 %\"{}\" to i64", sx, len32));
    // str_view build
    let vn = b.uniq_label("str_view");
    b.reg_names.push(vn.clone());
    if IN_FN.with(|v| *v.borrow()) {
        FN_ALLOCAS.with(|f| f.borrow_mut().push((vn.clone(), "view".into())));
    } else {
        MAIN_ALLOCAS.with(|m| m.borrow_mut().push(vn.clone()));
    }
    for fld in [0u32, 1, 3] {
        let g = b.nx();
        b.line(format!(
            "  %\"{}\" = getelementptr {{i64, i64, i8*, i64}}, {{i64, i64, i8*, i64}}* %\"{}\", i32 0, i32 {}",
            g, vn, fld));
        b.silent();
        b.line(format!("  store i64 %\"{}\", i64* %\"{}\"", sx, g));
    }
    let g2 = b.nx();
    b.line(format!(
        "  %\"{}\" = getelementptr {{i64, i64, i8*, i64}}, {{i64, i64, i8*, i64}}* %\"{}\", i32 0, i32 2",
        g2, vn));
    b.silent();
    b.line(format!("  store i8* %\"{}\", i8** %\"{}\"", chars, g2));
    let vbc = b.nx();
    b.line(format!(
        "  %\"{}\" = bitcast {{i64, i64, i8*, i64}}* %\"{}\" to i8*",
        vbc, vn));
    let res = b.nx();
    match def {
        Some(d) => b.line(format!(
            "  %\"{}\" = call i64 @\"rawdict_str_get_or\"(i8* {}, i8* %\"{}\", i64 {})",
            res, dl, vbc, d)),
        None => b.line(format!(
            "  %\"{}\" = call i64 @\"rawdict_str_get\"(i8* {}, i8* %\"{}\")",
            res, dl, vbc)),
    }
    format!("%\"{}\"", res)
}

fn as_slice_sub(v: &Val) -> Option<(String, Val)> {
    if v.head() == "subscript" && v.get(1).head() == "name"
        && v.get(2).head() == "slice" {
        Some((v.get(1).get(1).str_of(), v.get(2).clone()))
    } else if v.head() == "slice" {
        Some((String::new(), v.clone())) // base decided by caller
    } else { None }
}

fn emit_slice_view(b: &mut FnB, base: &str, sl: &Val, sc: &mut usize) -> String {
    let fs = F_SLOTS.with(|f| f.borrow().clone());
    let l = b.nx();
    b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, base));
    unsafe { SC_PTR = sc; }
    let sv = eval_expr(b, &sl.get(1), &global_slot, &global_slot, sc, &fs);
    let Typed::I64(sref) = sv else { bail("slice start") };
    let ev = eval_expr(b, &sl.get(2), &global_slot, &global_slot, sc, &fs);
    let Typed::I64(eref) = ev else { bail("slice end") };
    let sp = b.nx();
    b.line(format!(
        "  %\"{}\" = call {{i8*, i64}} @\"rawstr_slice_parts\"(i8* %\"{}\", i64 {}, i64 {})",
        sp, l, sref, eref));
    let d = b.nx();
    b.line(format!(
        "  %\"{}\" = extractvalue {{i8*, i64}} %\"{}\", 0", d, sp));
    let ln = b.nx();
    b.line(format!(
        "  %\"{}\" = extractvalue {{i8*, i64}} %\"{}\", 1", ln, sp));
    let vn = b.uniq_label("str_view");
    b.reg_names.push(vn.clone());
    if IN_FN.with(|v| *v.borrow()) {
        FN_ALLOCAS.with(|f| f.borrow_mut().push((vn.clone(), "view".into())));
    } else {
        MAIN_ALLOCAS.with(|m| m.borrow_mut().push(vn.clone()));
    }
    for fld in [0u32, 1, 3] {
        let g = b.nx();
        b.line(format!(
            "  %\"{}\" = getelementptr {{i64, i64, i8*, i64}}, {{i64, i64, i8*, i64}}* %\"{}\", i32 0, i32 {}",
            g, vn, fld));
        b.silent();
        b.line(format!("  store i64 %\"{}\", i64* %\"{}\"", ln, g));
    }
    let g2 = b.nx();
    b.line(format!(
        "  %\"{}\" = getelementptr {{i64, i64, i8*, i64}}, {{i64, i64, i8*, i64}}* %\"{}\", i32 0, i32 2",
        g2, vn));
    b.silent();
    b.line(format!("  store i8* %\"{}\", i8** %\"{}\"", d, g2));
    let bc = b.nx();
    b.line(format!(
        "  %\"{}\" = bitcast {{i64, i64, i8*, i64}}* %\"{}\" to i8*",
        bc, vn));
    format!("%\"{}\"", bc)
}

fn eval_mod(b: &mut FnB, e: &Val, fslots: &[String], sc: &mut usize) -> Typed {
    // json_* builtins over the tagged-union Json representation
    // (jsonparse_json). The Json value is an i8* tagged block pointer.
    if e.head() == "call" && e.get(1).head() == "name" {
        let fname = e.get(1).get(1).str_of();
        let jargs = e.get(2).items();
        if jargs.len() == 1 && fname.starts_with("json_") {
            let av = eval_mod(b, &jargs[0], fslots, sc);
            let jv = match av {
                Typed::Inst(r) | Typed::Str(r) => r,
                Typed::I64(r) => r, // already a slot pointer (it=items[i])
                _ => bail("json arg"),
            };
            match fname.as_str() {
                "json_tag" => {
                    let t = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i32 @\"tagged_tag\"(i8* {})", t, jv));
                    let sx = b.nx();
                    b.line(format!(
                        "  %\"{}\" = sext i32 %\"{}\" to i64", sx, t));
                    return Typed::I64(format!("%\"{}\"", sx));
                }
                "json_int" => {
                    let c = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i64 @\"json_unwrap_int\"(i8* {})", c, jv));
                    return Typed::I64(format!("%\"{}\"", c));
                }
                "json_str" => {
                    // borrowed str payload, then copy into a raw str
                    let bw = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i8* @\"json_unwrap_str\"(i8* {})", bw, jv));
                    let cp = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i8* @\"rawstr_copy\"(i8* %\"{}\")", cp, bw));
                    return Typed::Str(format!("%\"{}\"", cp));
                }
                "json_list" | "json_dict" => {
                    let f = if fname == "json_list" { "json_unwrap_list" }
                            else { "json_unwrap_dict" };
                    let c = b.nx();
                    b.line(format!(
                        "  %\"{}\" = call i8* @\"{}\"(i8* {})", c, f, jv));
                    return Typed::Inst(format!("%\"{}\"", c));
                }
                "json_free" => {
                    b.silent();
                    b.line(format!(
                        "  call void @\"tagged_free\"(i8* {}, i32 4, i32 5, i32 6)", jv));
                    return Typed::I64("0".into());
                }
                _ => {}
            }
        }
    }
    if e.head() == "name" {
        let n = e.get(1).str_of();
        let l = b.nx();
        if is_local_s(&n) {
            b.line(format!("  %\"{}\" = load i8*, i8** %\"{}\"", l, n));
            return Typed::Str(format!("%\"{}\"", l));
        }
        if FN_L.with(|t| t.borrow().iter().any(|(k, _)| k == &n)) {
            b.line(format!("  %\"{}\" = load i8*, i8** %\"{}\"", l, n));
            return Typed::Inst(format!("%\"{}\"", l));
        }
        if FN_D.with(|t| t.borrow().iter().any(|k| k == &n)) {
            b.line(format!("  %\"{}\" = load i8*, i8** %\"{}\"", l, n));
            return Typed::Inst(format!("%\"{}\"", l));
        }
        if is_py(&n) {
            b.line(format!(
                "  %\"{}\" = load {{i32, i8*}}*, {{i32, i8*}}** {}",
                l, py_slot(&n)));
            return Typed::Pyo(format!("%\"{}\"", l));
        }
        if JSON_SLOTS.with(|t| t.borrow().iter().any(|x| x == &n)) {
            b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, n));
            return Typed::Inst(format!("%\"{}\"", l));
        }
        if fn_ty_of(&n).is_some() {
            if n == "self" || inst_stor(&n).is_none() {
                b.line(format!("  %\"{}\" = load i8*, i8** %\"{}\"",
                    l, n));
                return Typed::Inst(format!("%\"{}\"", l));
            }
            match inst_stor(&n).as_deref() {
                Some("i8*") => {
                    b.line(format!(
                        "  %\"{}\" = load i8*, i8** %\"{}\"", l, n));
                    return Typed::Inst(format!("%\"{}\"", l));
                }
                _ => {
                    b.line(format!(
                        "  %\"{}\" = load i64, i64* %\"{}\"", l, n));
                    return Typed::I64(format!("%\"{}\"", l));
                }
            }
        }
        if is_local_f(&n) {
            b.line(format!("  %\"{}\" = load double, double* %\"{}\"", l, n));
            return Typed::F64(format!("%\"{}\"", l));
        }
        if STR_SLOTS.with(|s| s.borrow().iter().any(|f| f == &n)) {
            b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, n));
            return Typed::Str(format!("%\"{}\"", l));
        }
        if fslots.iter().any(|f| f == &n) {
            b.line(format!("  %\"{}\" = load double, double* @\"{}\"", l, n));
            return Typed::F64(format!("%\"{}\"", l));
        }
        if is_local_i(&n) {
            b.line(format!("  %\"{}\" = load i64, i64* %\"{}\"", l, n));
            return Typed::I64(format!("%\"{}\"", l));
        }
        b.line(format!("  %\"{}\" = load i64, i64* @\"{}\"", l, n));
        return Typed::I64(format!("%\"{}\"", l));
    }
    if e.head() == "call" && e.get(1).head() == "name"
        && e.get(1).get(1).str_of() == "len" {
        let ia = e.get(2).items();
        if ia.len() != 1 { bail("len arg"); }
        // len(subscript): list-element str read then header len load
        if ia[0].head() == "subscript" && ia[0].get(1).head() == "name" {
            let bn = ia[0].get(1).get(1).str_of();
            if LST_SLOTS.with(|t| t.borrow().iter().any(|f| f == &bn))
                && lst_elem_ty(&bn) == "str" {
                let l = b.nx();
                b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", l, bn));
                unsafe { SC_PTR = sc; }
                let k = b.expr_i64(&ia[0].get(2), &global_slot);
                let d = b.nx();
                b.line(format!("  %\"{}\" = call i8* @\"rawlist_str_get\"(i8* %\"{}\", i64 {})",
                    d, l, k));
                let bc = b.nx();
                b.line(format!(
                    "  %\"{}\" = bitcast i8* %\"{}\" to {{i64, i64, i8*, i64}}*", bc, d));
                let gl = b.nx();
                b.line(format!(
                    "  %\"{}\" = getelementptr {{i64, i64, i8*, i64}}, {{i64, i64, i8*, i64}}* %\"{}\", i32 0, i32 3",
                    gl, bc));
                let ld = b.nx();
                b.line(format!("  %\"{}\" = load i64, i64* %\"{}\"", ld, gl));
                return Typed::I64(format!("%\"{}\"", ld));
            }
        }
        if ia[0].head() != "name" { bail("len arg"); }
        let n = ia[0].get(1).str_of();
        if is_py(&n) {
            let l = b.nx();
            b.line(format!(
                "  %\"{}\" = load {{i32, i8*}}*, {{i32, i8*}}** @\"{}\"",
                l, n));
            let c = b.nx();
            b.line(format!(
                "  %\"{}\" = call i64 @\"pyobj_len_raw\"({{i32, i8*}}* %\"{}\")",
                c, l));
            return Typed::I64(format!("%\"{}\"", c));
        }
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
        if STR_SLOTS.with(|s| s.borrow().iter().any(|f| f == &n))
            || is_local_s(&n) {
            let l = b.nx();
            let slot = if is_local_s(&n) { format!("%\"{}\"", n) }
                       else { format!("@\"{}\"", n) };
            b.line(format!("  %\"{}\" = load i8*, i8** {}", l, slot));
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
    if e.head() == "const" && matches!(e.get(1), Val::Str(_)) {
        // str constant -> pystr (create_str chain); concat/to_rawstr later
        let text = e.get(1).str_of();
        let gname = add_str(sc, &text);
        let blen = text.chars().count();
        let g = b.nx();
        b.line(format!(
            "  %\"{}\" = getelementptr [{} x i8], [{} x i8]* @\"{}\", i32 0, i32 0",
            g, blen + 1, blen + 1, gname));
        let c = b.nx();
        b.line(format!(
            "  %\"{}\" = call {{i32, i8*}}* @\"create_str\"(i8* %\"{}\", i32 {})",
            c, g, blen));
        return Typed::PStr(format!("%\"{}\"", c));
    }
    if e.head() == "call" && e.get(1).head() == "name"
        && e.get(1).get(1).str_of() == "str" {
        // str(int): create_int + pyobj_str_conv -> pystr
        let ia = e.get(2).items();
        if ia.len() != 1 { bail("str arity"); }
        let fs = F_SLOTS.with(|f| f.borrow().clone());
        let v = eval_expr(b, &ia[0],
            &|n: &str| format!("@\"{}\"", n),
            &|n: &str| format!("@\"{}\"", n), sc, &fs);
        let Typed::I64(r) = v else { bail("str arg type") };
        let c = b.nx();
        b.line(format!(
            "  %\"{}\" = call {{i32, i8*}}* @\"create_int\"(i64 {})", c, r));
        let cv = b.nx();
        b.line(format!(
            "  %\"{}\" = call {{i32, i8*}}* @\"pyobj_str_conv\"({{i32, i8*}}* %\"{}\")",
            cv, c));
        return Typed::PStr(format!("%\"{}\"", cv));
    }
    if e.head() == "call" && e.get(1).head() == "attribute"
        && e.get(1).get(2).str_of() == "get"
        && e.get(1).get(1).head() == "name"
        && DCT_SLOTS.with(|t| t.borrow().iter()
            .any(|f| f == &e.get(1).get(1).get(1).str_of())) {
        // d.get(key, default) on a str-keyed dict: rawdict_str_entry,
        // bitcast, load value (wordcount print arg evidence)
        let d = e.get(1).get(1).get(1).str_of();
        let args = e.get(2).items();
        if args.len() != 2 { bail("get arity"); }
        let dl = b.nx();
        b.line(format!("  %\"{}\" = load i8*, i8** @\"{}\"", dl, d));
        let fs = F_SLOTS.with(|f| f.borrow().clone());
        if args[0].head() == "const" && matches!(args[0].get(1), Val::Str(_)) {
            let text = args[0].get(1).str_of();
            let def = args[1].get(1).int_of();
            let r = emit_const_key_get(b, &format!("%\"{}\"", dl), &text, def, sc);
            return Typed::I64(r);
        }
        let kr = if let Some((bname, sl)) = as_slice_sub(&args[0]) {
            emit_slice_view(b, &bname, &sl, sc)
        } else {
            let kv = eval_mod(b, &args[0], &fs, sc);
            to_raw(b, kv, sc)
        };
        if !matches!(args[1].get(1), Val::Int(_)) { bail("get default"); }
        let en = b.nx();
        b.line(format!(
            "  %\"{}\" = call i8* @\"rawdict_str_entry\"(i8* %\"{}\", i8* {}, i64 {})",
            en, dl, kr, args[1].get(1).int_of()));
        let bc = b.nx();
        b.line(format!(
            "  %\"{}\" = bitcast i8* %\"{}\" to i64*", bc, en));
        let ld = b.nx();
        b.line(format!(
            "  %\"{}\" = load i64, i64* %\"{}\"", ld, bc));
        return Typed::I64(format!("%\"{}\"", ld));
    }
    if e.head() == "call" && e.get(1).head() == "name"
        && e.get(1).get(1).str_of() != "len" {
        // typed user call (signatures collected before conversion)
        return eval_expr(b, e,
            &|n: &str| format!("@\"{}\"", n),
            &|n: &str| format!("@\"{}\"", n), sc, fslots);
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

    // Json / tagged-union detection: any annotation mentioning the Json
    // type (return, param, local, list/dict element) pulls in the tagged
    // runtime block and shifts the global-slot base
    fn uses_json(v: &Val) -> bool {
        if let Val::List(items) = v {
            for it in items.iter() {
                if matches!(it, Val::Str(s) if s == "Json") { return true; }
                if uses_json(it) { return true; }
            }
        }
        false
    }
    let tagged = uses_json(&Val::List(stmts.clone()));
    TAGGED.with(|t| *t.borrow_mut() = tagged);
    let mut sc = STR_BASE + if tagged { TAGGED_SLOTS } else { 0 };
    // dynamic classes: consumed via match_class -> pyobj instances
    fn scan_match(v: &Val) {
        if let Val::List(items) = v {
            if v.head() == "match_class" {
                let cn = v.get(1).get(1).str_of();
                if !DYN_CLASSES.with(|d| d.borrow().iter().any(|x| *x == cn)) {
                    DYN_CLASSES.with(|d| d.borrow_mut().push(cn));
                }
            }
            for i in items { scan_match(i); }
        }
    }
    for st in stmts.iter() { scan_match(st); }
    // registries first: classes/enums must exist before signature typing
    for st in stmts.iter() {
        if st.head() == "enum_def" {
            let variants: Vec<String> = st.get(2).items().iter()
                .map(|v| v.get(0).str_of()).collect();
            let ename = st.get(1).str_of();
            if !ENUMS.with(|m| m.borrow().iter()
                    .any(|(k, _)| *k == ename)) {
                ENUMS.with(|m| m.borrow_mut().push((ename, variants)));
            }
        }
        if st.head() == "class_def" {
            let cname = st.get(1).str_of();
            if !CLASSES.with(|c| c.borrow().iter()
                    .any(|(k, _)| *k == cname)) {
                let body = st.get(3).items();
                let mut fields: Vec<(String, String)> = Vec::new();
                for b in body.iter() {
                    if b.head() == "ann_assign" {
                        let an = b.get(3);
                        let t = if an.head() == "subscript"
                            && an.get(1).get(1).str_of() == "list" {
                            format!("list:{}", an.get(2).get(1).str_of())
                        } else { an.get(1).str_of() };
                        fields.push((b.get(1).str_of(), t));
                    }
                }
                CLASSES.with(|c| c.borrow_mut()
                    .push((cname.clone(), fields)));
                for b in body.iter() {
                    if b.head() == "func_def" {
                        let mname = format!("{}__{}",
                            cname, b.get(1).str_of());
                        let mut items = b.items();
                        items[1] = Val::Str(mname);
                        if let Val::List(annos) = &mut items[4] {
                            if !annos.is_empty() {
                                annos[0] = Val::List(vec![
                                    Val::Str("name".into()),
                                    Val::Str(cname.clone())]);
                            }
                        }
                        FUNC_DEFS.with(|f| f.borrow_mut()
                            .push(Val::List(items)));
                    }
                }
            }
        }
    }
    // pyobj-returning functions: fixpoint (ctor returns, then callers)
    {
        let fdefs: Vec<&Val> = stmts.iter()
            .filter(|st| st.head() == "func_def").collect();
        loop {
            let mut added = false;
            for fd in fdefs.iter() {
                let nm = fd.get(1).str_of();
                if PY_RETS.with(|r| r.borrow().iter().any(|x| *x == nm)) {
                    continue;
                }
                let is_py_ret = infer_ret(&fd.get(3).items(),
                    &fd.get(2).items(), &fd.get(4).items()) == "pyobj";
                if is_py_ret {
                    PY_RETS.with(|r| r.borrow_mut().push(nm.clone()));
                    added = true;
                }
            }
            // propagate: bodies whose returns call PY_RETS functions
            for fd in fdefs.iter() {
                let nm = fd.get(1).str_of();
                if PY_RETS.with(|r| r.borrow().iter().any(|x| *x == nm)) {
                    continue;
                }
                let mut hits_py_call = false;
                fn walk_ret(v: &Val, py: &[String]) -> bool {
                    if let Val::List(items) = v {
                        if v.head() == "return" {
                            let r = v.get(1);
                            if r.head() == "call" && r.get(1).head() == "name"
                                && py.iter()
                                    .any(|p| *p == r.get(1).get(1).str_of()) {
                                return true;
                            }
                        }
                        for i in items { if walk_ret(i, py) { return true; } }
                    }
                    false
                }
                let pys = PY_RETS.with(|r| r.borrow().clone());
                hits_py_call = walk_ret(fd, &pys);
                if hits_py_call {
                    PY_RETS.with(|r| r.borrow_mut().push(nm.clone()));
                    added = true;
                }
            }
            if !added { break; }
        }
    }
    // signatures first: main may call functions defined later
    let sig_of = |fd: &Val, prefix: Option<&str>| {
        let atys: Vec<String> = fd.get(4).items().iter().enumerate()
            .map(|(i, a)| {
                if i == 0 {
                    if let Some(cls) = prefix {
                        return format!("inst:{}", cls);
                    }
                }
                if a.head() == "subscript"
                    && a.get(1).get(1).str_of() == "list" {
                    let el = a.get(2).get(1).str_of();
                    format!("list:{}", if el == "Json" { "json".into() } else { el })
                } else {
                    let t = a.get(1).str_of();
                    if t == "Json" { "json".into() }
                    else if is_class(&t) { format!("inst:{}", t) }
                    else if is_enum(&t) { "int".into() }
                    else { t }
                }
            }).collect();
        let rt0 = if matches!(fd.get(5), Val::Null) {
            infer_ret(&fd.get(3).items(), &fd.get(2).items(),
                      &fd.get(4).items())
        }
                 else if fd.get(5).head() == "subscript"
                     && fd.get(5).get(1).get(1).str_of() == "list" {
                     let el = fd.get(5).get(2).get(1).str_of();
                     format!("list:{}", if el == "Json" { "json".into() } else { el })
                 } else { fd.get(5).get(1).str_of() };
        let rt = if rt0 == "Json" { "json".into() }
                 else if is_class(&rt0) { format!("inst:{}", rt0) } else { rt0 };
        let name = match prefix {
            Some(c) => format!("{}__{}", c, fd.get(1).str_of()),
            None => fd.get(1).str_of(),
        };
        FN_SIGS.with(|m| m.borrow_mut().push((name, atys, rt)));
    };
    for st in stmts.iter() {
        if st.head() == "func_def" { sig_of(st, None); }
        if st.head() == "class_def" {
            let cname = st.get(1).str_of();
            for b2 in st.get(3).items().iter() {
                if b2.head() == "func_def" { sig_of(b2, Some(&cname)); }
            }
        }
    }
    let func_defs = walk_module(&stmts, &mut sc);

    let mut out = String::new();
    out.push_str(CONST_PREFIX);
    if TAGGED.with(|t| *t.borrow()) {
        out.push_str(TAGGED_PREFIX);
        out.push('\n'); // blank line before the first user function
    }
    for fd in &func_defs {
        out.push_str(&convert_func(fd, &mut sc));
    }
    unsafe {
        let mo = MAIN_OUT.as_ref().unwrap();
        let has_user_main = FUNC_DEFS.with(|f| f.borrow().iter()
            .any(|fd| fd.get(1).str_of() == "main"));
        out.push_str(mo);
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
