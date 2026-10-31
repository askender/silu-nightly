// silu-conv: R2 milestone - typed converter for the pinned snapshot
// (silu 1.16.2 / 87df40f), fib-subset. Reads a .si path, gets IR JSON
// from the verified silu-fe sibling, emits const_prefix.ll + user
// functions + main + user globals. Constructs outside the subset exit
// 3 (harness reports ERROR, never wrong bytes).
//
// Slot rule (README): EVERY instruction consumes one scope slot; void
// ones (store/br/cbr/ret/void-call/unreachable) consume silently.

use std::cell::RefCell;
use std::env;
use std::io::Write;
use std::process::Command;

const CONST_PREFIX: &str = include_str!("../../const_prefix.ll");
const STR_BASE: usize = 298;

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
    fn str_of(&self) -> String { match self { Val::Str(s) => s.clone(), _ => String::new() } }
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
                        'n' => out.push('\n'),
                        't' => out.push('\t'),
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

fn nx(a: &mut usize) -> String { *a += 1; format!(".{}", *a) }

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
    let line = format!("@\"{}\" = constant [{} x i8] c\"{}\"",
                      name, bytes.len(), escape_bytes(bytes.as_bytes()));
    STRS.with(|s| s.borrow_mut().push(line));
    name
}

// ---------- fib-subset converter ----------

fn convert_func(fd: &Val, sc: &mut usize) -> String {
    let name = fd.get(1).str_of();
    let params = fd.get(2).items();
    let annos = fd.get(4).items();
    let ret_anno = fd.get(5);
    let body = fd.get(3).items();

    if params.len() != annos.len() { bail("param/anno mismatch"); }
    for (p, a) in params.iter().zip(annos.iter()) {
        if !(a.head() == "name" && a.get(1).str_of() == "int") || p.str_of().is_empty() {
            bail("non-int param");
        }
    }
    if !(ret_anno.head() == "name" && ret_anno.get(1).str_of() == "int") {
        bail("non-int return");
    }

    let n = params.len();
    let mut anon = n + 1; // .1..N args, .N+1 ret slot (silent)

    let mut out = String::new();
    out.push_str(&format!(
        "define internal i64 @\"{}\"({}) alwaysinline\n{{\nentry:\n",
        name,
        (1..=n).map(|i| format!("i64 %\".{}\"", i))
            .collect::<Vec<_>>().join(", ")));
    for p in params.iter().rev() {
        out.push_str(&format!("  %\"{}\" = alloca i64\n", p.str_of()));
    }
    for (i, p) in params.iter().enumerate() {
        let _ = nx(&mut anon); // store: silent slot
        out.push_str(&format!("  store i64 %\".{}\", i64* %\"{}\"\n", i + 1, p.str_of()));
    }

    let mut bi = 0usize;
    while bi < body.len() {
        let st = body[bi].clone();
        if st.head() == "line" {
            let _ = nx(&mut anon);
            out.push_str(&format!("  store i64 {}, i64* @\"__silu_line\"\n", st.get(1).int_of()));
            bi += 1;
            continue;
        }
        match st.head() {
            "if" => {
                let cond = st.get(1);
                let then_body = st.get(2).items();
                let orelse = st.get(3).items();
                let pred = match cond.head() {
                    "<" => "slt", "<=" => "sle", ">" => "sgt", ">=" => "sge",
                    _ => bail("if cond op"),
                };
                let lhs = expr_i64(&cond.get(1), &mut out, &mut anon);
                let rhs = expr_i64(&cond.get(2), &mut out, &mut anon);
                let ic = nx(&mut anon);
                out.push_str(&format!("  %\"{}\" = icmp {} i64 {}, {}\n", ic, pred, lhs, rhs));
                let _ = nx(&mut anon); // cbr silent
                out.push_str(&format!(
                    "  br i1 %\"{}\", label %\"if_then\", label %\"if_else\"\n", ic));
                out.push_str("if_then:\n");
                emit_then(&then_body, &mut out, &mut anon);
                if !orelse.is_empty() { bail("non-empty else"); }
                let _ = nx(&mut anon); // br silent
                out.push_str("if_else:\n  br label %\"if_merge\"\n");
                out.push_str("if_merge:\n");
            }
            "return" => {
                let v = st.get(1);
                match v.head() {
                    "name" => {
                        let l = nx(&mut anon);
                        out.push_str(&format!("  %\"{}\" = load i64, i64* %\"{}\"\n",
                                              l, v.get(1).str_of()));
                        let _ = nx(&mut anon); // ret silent
                        out.push_str(&format!("  ret i64 %\"{}\"\n", l));
                    }
                    "+" => {
                        let a = checked_binop(&v, &mut out, &mut anon, sc, "add");
                        let _ = nx(&mut anon); // ret silent
                        out.push_str(&format!("  ret i64 {}\n", a));
                    }
                    _ => bail("return expr"),
                }
            }
            _ => bail(st.head()),
        }
        bi += 1;
    }
    out.push_str("}\n\n");
    out
}

fn expr_i64(e: &Val, out: &mut String, anon: &mut usize) -> String {
    match e.head() {
        "name" => {
            let l = nx(anon);
            out.push_str(&format!("  %\"{}\" = load i64, i64* %\"{}\"\n",
                                  l, e.get(1).str_of()));
            format!("%\"{}\"", l)
        }
        "const" if matches!(e.get(1), Val::Int(_)) => e.get(1).int_of().to_string(),
        _ => bail("cond expr"),
    }
}

fn checked_binop(v: &Val, out: &mut String, anon: &mut usize,
                 sc: &mut usize, which: &str) -> String {
    let lhs_e = v.get(1);
    let rhs_e = v.get(2);
    let lhs = match lhs_e.head() {
        "name" => {
            let l = nx(anon);
            out.push_str(&format!("  %\"{}\" = load i64, i64* %\"{}\"\n", l, lhs_e.get(1).str_of()));
            format!("%\"{}\"", l)
        }
        "call" => conv_call(&lhs_e, out, anon, sc),
        "const" if matches!(lhs_e.get(1), Val::Int(_)) => lhs_e.get(1).int_of().to_string(),
        _ => bail("binop lhs"),
    };
    let rhs = match rhs_e.head() {
        "name" => {
            let l = nx(anon);
            out.push_str(&format!("  %\"{}\" = load i64, i64* %\"{}\"\n", l, rhs_e.get(1).str_of()));
            format!("%\"{}\"", l)
        }
        "call" => conv_call(&rhs_e, out, anon, sc),
        "-" => checked_binop(&rhs_e, out, anon, sc, "sub"),
        "const" if matches!(rhs_e.get(1), Val::Int(_)) => rhs_e.get(1).int_of().to_string(),
        _ => bail("binop rhs"),
    };
    let (intrinsic, msg) = if which == "add" {
        ("llvm.sadd.with.overflow.i64", "OverflowError: integer overflow in add")
    } else {
        ("llvm.ssub.with.overflow.i64", "OverflowError: integer overflow in sub")
    };
    let c = nx(anon);
    out.push_str(&format!(
        "  %\"{}\" = call {{i64, i1}} @\"{}\"(i64 {}, i64 {})\n", c, intrinsic, lhs, rhs));
    let v0 = nx(anon);
    out.push_str(&format!("  %\"{}\" = extractvalue {{i64, i1}} %\"{}\", 0\n", v0, c));
    let v1 = nx(anon);
    out.push_str(&format!("  %\"{}\" = extractvalue {{i64, i1}} %\"{}\", 1\n", v1, c));
    let _ = nx(anon); // cbr silent
    // dedupe suffix: previous DISTINCT panic_bad labels already suffixed;
    // matches() on the emitted text counts label mentions in cbr too,
    // so count only label-definition lines
    let bad_count = out.lines().filter(|l| l.starts_with("panic_bad")).count();
    let suffix = if bad_count == 0 { String::new() } else { format!(".{}", bad_count) };
    out.push_str(&format!(
        "  br i1 %\"{}\", label %\"panic_bad{}\", label %\"panic_ok{}\"\n", v1, suffix, suffix));
    let msg_name = add_str(sc, msg);
    out.push_str(&format!("panic_bad{}:\n", suffix));
    let g = nx(anon);
    let msg_len = msg.len() + 1;
    out.push_str(&format!(
        "  %\"{}\" = getelementptr [{} x i8], [{} x i8]* @\"{}\", i32 0, i32 0\n",
        g, msg_len, msg_len, msg_name));
    let _ = nx(anon); // void call silent
    out.push_str(&format!("  call void @\"silu_panic\"(i8* %\"{}\")\n", g));
    let _ = nx(anon); // unreachable silent
    out.push_str("  unreachable\n");
    out.push_str(&format!("panic_ok{}:\n", suffix));
    format!("%\"{}\"", v0)
}

fn conv_call(call: &Val, out: &mut String, anon: &mut usize, sc: &mut usize) -> String {
    let fname = call.get(1).get(1).str_of();
    let args = call.get(2).items();
    if args.len() != 1 { bail("call arity"); }
    let arg = &args[0];
    let arg_s = match arg.head() {
        "const" if matches!(arg.get(1), Val::Int(_)) => format!("i64 {}", arg.get(1).int_of()),
        "-" => {
            let inner = checked_binop(arg, out, anon, sc, "sub");
            format!("i64 {}", inner)
        }
        _ => bail("call arg"),
    };
    let c = nx(anon);
    out.push_str(&format!("  %\"{}\" = call i64 @\"{}\"({})\n", c, fname, arg_s));
    format!("%\"{}\"", c)
}

fn emit_then(body: &[Val], out: &mut String, anon: &mut usize) {
    let mut i = 0usize;
    while i < body.len() {
        let st = body[i].clone();
        if st.head() == "line" {
            let _ = nx(anon);
            out.push_str(&format!("  store i64 {}, i64* @\"__silu_line\"\n", st.get(1).int_of()));
            i += 1;
            continue;
        }
        if st.head() == "return" && st.get(1).head() == "name" {
            let l = nx(anon);
            out.push_str(&format!("  %\"{}\" = load i64, i64* %\"{}\"\n",
                                  l, st.get(1).get(1).str_of()));
            let _ = nx(anon); // ret silent
            out.push_str(&format!("  ret i64 %\"{}\"\n", l));
            i += 1;
            continue;
        }
        bail("then body stmt");
    }
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
    let mut func_defs: Vec<Val> = Vec::new();
    let mut main_lines: Vec<String> = Vec::new();
    let mut main_anon = 1usize; // .1 = main's ret slot (silent)

    // module walk FIRST: module-level statements create their strings
    // during the walk; function bodies are generated afterward (the
    // reference's generate_function_bodies phase) - so a print's
    // strings number BELOW the function bodies' panic messages.
    for st in &stmts {
        if !matches!(st, Val::List(_)) { continue; }
        match st.head() {
            "line" => {
                let _ = nx(&mut main_anon);
                main_lines.push(format!("  store i64 {}, i64* @\"__silu_line\"",
                                       st.get(1).int_of()));
            }
            "func_def" => {
                func_defs.push(st.clone());
            }
            "call" if st.get(1).head() == "name" && st.get(1).get(1).str_of() == "print" => {
                let args = st.get(2).items();
                if args.len() != 1 { bail("print arity"); }
                let a = &args[0];
                if !(a.head() == "call" && a.get(1).head() == "name") {
                    bail("print arg");
                }
                let inner_args = a.get(2).items();
                if inner_args.len() != 1
                    || inner_args[0].head() != "const"
                    || !matches!(inner_args[0].get(1), Val::Int(_))
                {
                    bail("print arg detail");
                }
                let c = nx(&mut main_anon);
                main_lines.push(format!("  %\"{}\" = call i64 @\"{}\"(i64 {})",
                    c, a.get(1).get(1).str_of(), inner_args[0].get(1).int_of()));
                let fmt_name = add_str(&mut sc, "%lld");
                let g = nx(&mut main_anon);
                main_lines.push(format!(
                    "  %\"{}\" = getelementptr [5 x i8], [5 x i8]* @\"{}\", i32 0, i32 0",
                    g, fmt_name));
                let p = nx(&mut main_anon);
                main_lines.push(format!(
                    "  %\"{}\" = call i32 (i8*, ...) @\"printf\"(i8* %\"{}\", i64 %\"{}\")",
                    p, g, c));
                let nl_name = add_str(&mut sc, "\x0a");
                let g2 = nx(&mut main_anon);
                main_lines.push(format!(
                    "  %\"{}\" = getelementptr [2 x i8], [2 x i8]* @\"{}\", i32 0, i32 0",
                    g2, nl_name));
                let p2 = nx(&mut main_anon);
                main_lines.push(format!(
                    "  %\"{}\" = call i32 (i8*, ...) @\"printf\"(i8* %\"{}\")", p2, g2));
            }
            _ => bail(st.head()),
        }
    }

    let mut out = String::new();
    out.push_str(CONST_PREFIX);
    for fd in &func_defs {
        out.push_str(&convert_func(fd, &mut sc));
    }
    out.push_str("define i32 @\"main\"()\n{\nentry:\n");
    for l in &main_lines { out.push_str(l); out.push('\n'); }
    out.push_str("  ret i32 0\n}\n\n");
    STRS.with(|s| {
        let lines = s.borrow().clone();
        let last = lines.len();
        for (i, line) in lines.iter().enumerate() {
            out.push_str(line);
            if i + 1 < last { out.push('\n'); }
        }
    });
    let so = std::io::stdout();
    let mut lock = so.lock();
    let _ = lock.write_all(out.as_bytes());
}
