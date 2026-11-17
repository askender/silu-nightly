// silu-fe: an independent Rust implementation of the Silu front end,
// pinned to silu 1.16.2 (commit 87df40f) behavior. Reads a .si path,
// emits the tuple-IR as JSON on stdout - the differential harness
// compares it (canonically) against the self-hosted silu_fe.
//
// This is a deliberate TRANSLITERATION of selfhost/silu_fe.si: the
// shape mirrors the spec function-for-function so divergences are
// localized. Dynamic IR trees map onto a JSON-value enum.

use std::env;
use std::fs;
use std::io::Write;
use std::path::Path;
use std::rc::Rc;
use std::cell::RefCell;

// ---------- the IR value (Python dynamic tree mirror) ----------

#[derive(Clone, Debug, PartialEq)]
pub enum Val {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
    List(Vec<Val>),
}

impl Val {
    fn s(x: &str) -> Val { Val::Str(x.to_string()) }
    fn i(x: i64) -> Val { Val::Int(x) }
    fn f(x: f64) -> Val { Val::Float(x) }
    fn node(head: &str, rest: Vec<Val>) -> Val {
        let mut v = Vec::with_capacity(rest.len() + 1);
        v.push(Val::s(head));
        v.extend(rest);
        Val::List(v)
    }
    fn is_node(&self) -> bool {
        match self {
            Val::List(v) => !v.is_empty() && matches!(v[0], Val::Str(_)),
            _ => false,
        }
    }
    fn is_scalar(&self) -> bool { !matches!(self, Val::List(_)) }
    fn head(&self) -> &str {
        match self {
            Val::List(v) => match &v[0] { Val::Str(s) => s, _ => "" },
            _ => "",
        }
    }
    fn len(&self) -> usize {
        match self { Val::List(v) => v.len(), _ => 0 }
    }
    fn get(&self, k: usize) -> Val {
        match self { Val::List(v) => v.get(k).cloned().unwrap_or(Val::Null), _ => Val::Null }
    }
    fn as_str(&self) -> String {
        match self { Val::Str(s) => s.clone(), _ => String::new() }
    }
    fn str_or(&self) -> Option<String> {
        match self { Val::Str(s) => Some(s.clone()), _ => None }
    }
}

fn n0(head: &str) -> Val { Val::node(head, vec![]) }
fn ns2(a: &str, b: Val) -> Val { Val::node(a, vec![b]) }
fn ns3(a: &str, b: Val, c: Val) -> Val { Val::node(a, vec![b, c]) }

// ---------- lexer ----------

#[derive(Clone, Copy, PartialEq, Debug)]
enum TokKind { Name, Num, Str, Op, Kw, Nl, End, FStr, Bytes }

#[derive(Clone, Debug)]
struct Token { kind: TokKind, text: String, line: i64, col: i64 }

const KW: &[&str] = &[
    "def", "class", "if", "elif", "else", "while", "for", "in",
    "not", "and", "or", "return", "break", "continue", "pass",
    "import", "from", "raise", "is", "None", "True", "False",
    "lambda", "del", "assert", "with", "as", "try", "except",
    "finally", "global", "nonlocal", "yield", "async", "await",
];

struct Lexer { src: Vec<char>, pos: usize, line: i64, col: i64, depth: i64 }

impl Lexer {
    fn new(src: &str) -> Lexer {
        Lexer { src: src.chars().collect(), pos: 0, line: 1, col: 0, depth: 0 }
    }
    fn peek_cp(&self) -> i64 {
        if self.pos >= self.src.len() { -1 } else { self.src[self.pos] as i64 }
    }
    fn peek2_cp(&self) -> i64 {
        if self.pos + 1 >= self.src.len() { -1 } else { self.src[self.pos + 1] as i64 }
    }
    fn peek3_cp(&self) -> i64 {
        if self.pos + 2 >= self.src.len() { -1 } else { self.src[self.pos + 2] as i64 }
    }
    fn advance(&mut self) -> i64 {
        let c = self.peek_cp();
        self.pos += 1;
        if c == 10 { self.line += 1; self.col = 0; } else { self.col += 1; }
        c
    }
    fn skip_ws_and_comments(&mut self) {
        while self.pos < self.src.len() {
            let c = self.peek_cp();
            if c == 32 || c == 9 {
                self.advance();
            } else if c == 35 {
                while self.pos < self.src.len() && self.peek_cp() != 10 {
                    self.advance();
                }
            } else {
                return;
            }
        }
    }
    fn is_name_start_cp(&self, c: i64) -> bool {
        (97..=122).contains(&c) || (65..=90).contains(&c) || c == 95
    }
    fn is_name_char_cp(&self, c: i64) -> bool {
        self.is_name_start_cp(c) || (48..=57).contains(&c)
    }
    fn slice(&self, a: usize, b: usize) -> String {
        self.src[a..b].iter().collect()
    }
    fn next_token(&mut self) -> Token {
        self.skip_ws_and_comments();
        if self.pos >= self.src.len() {
            return Token { kind: TokKind::End, text: String::new(),
                           line: self.line, col: self.col };
        }
        let c = self.peek_cp();
        let line = self.line;
        let col = self.col;
        if c == 10 {
            self.advance();
            if self.depth > 0 {
                return self.next_token();
            }
            return Token { kind: TokKind::Nl, text: "\n".into(), line, col };
        }
        if (c == 98 || c == 66) && (self.peek2_cp() == 34 || self.peek2_cp() == 39) {
            let qb = self.peek2_cp();
            self.advance();
            self.advance();
            let startb = self.pos;
            while self.pos < self.src.len() && self.peek_cp() != qb {
                if self.peek_cp() == 92 { self.advance(); }
                self.advance();
            }
            let rawb = self.slice(startb, self.pos);
            self.advance();
            return Token { kind: TokKind::Bytes, text: rawb, line, col };
        }
        if (c == 102 || c == 70) && (self.peek2_cp() == 34 || self.peek2_cp() == 39) {
            let q0 = self.peek2_cp();
            self.advance();
            self.advance();
            let startf = self.pos;
            while self.pos < self.src.len() && self.peek_cp() != q0 {
                if self.peek_cp() == 92 { self.advance(); }
                self.advance();
            }
            let rawf = self.slice(startf, self.pos);
            self.advance();
            return Token { kind: TokKind::FStr, text: rawf, line, col };
        }
        if self.is_name_start_cp(c) {
            let start = self.pos;
            while self.pos < self.src.len() && self.is_name_char_cp(self.peek_cp()) {
                self.advance();
            }
            let text = self.slice(start, self.pos);
            let kind = if KW.contains(&text.as_str()) { TokKind::Kw } else { TokKind::Name };
            return Token { kind, text, line, col };
        }
        if (48..=57).contains(&c) {
            let start = self.pos;
            let nxt = self.peek2_cp();
            if c == 48 && (nxt == 120 || nxt == 88) {
                self.advance();
                self.advance();
                while self.pos < self.src.len() {
                    let d = self.peek_cp();
                    if (48..=57).contains(&d) || (97..=102).contains(&d) || (65..=70).contains(&d) {
                        self.advance();
                    } else { break; }
                }
                return Token { kind: TokKind::Num, text: self.slice(start, self.pos), line, col };
            }
            if c == 48 && (nxt == 98 || nxt == 66 || nxt == 111 || nxt == 79) {
                self.advance();
                self.advance();
                while self.pos < self.src.len() {
                    let d = self.peek_cp();
                    if (48..=57).contains(&d) || d == 95 {
                        self.advance();
                    } else { break; }
                }
                return Token { kind: TokKind::Num, text: self.slice(start, self.pos), line, col };
            }
            let mut seen_dot = false;
            let mut seen_exp = false;
            while self.pos < self.src.len() {
                let d = self.peek_cp();
                if (48..=57).contains(&d) || d == 95 {
                    self.advance();
                } else if d == 46 && !seen_dot && !seen_exp && self.peek2_cp() != 46 {
                    seen_dot = true;
                    self.advance();
                } else if (d == 101 || d == 69) && !seen_exp {
                    seen_exp = true;
                    self.advance();
                    let nxt2 = self.peek_cp();
                    if nxt2 == 43 || nxt2 == 45 {
                        self.advance();
                    }
                } else {
                    return Token { kind: TokKind::Num, text: self.slice(start, self.pos), line, col };
                }
            }
            return Token { kind: TokKind::Num, text: self.slice(start, self.pos), line, col };
        }
        if c == 34 || c == 39 {
            if self.peek2_cp() == c && self.peek3_cp() == c {
                self.advance();
                self.advance();
                self.advance();
                let start = self.pos;
                let mut closed = false;
                while self.pos < self.src.len() {
                    if self.peek_cp() == c && self.peek2_cp() == c && self.peek3_cp() == c {
                        closed = true;
                        break;
                    }
                    if self.peek_cp() == 92 { self.advance(); }
                    self.advance();
                }
                let text = self.slice(start, self.pos);
                if closed {
                    self.advance();
                    self.advance();
                    self.advance();
                }
                return Token { kind: TokKind::Str, text, line, col };
            }
            let q = self.advance();
            let start = self.pos;
            while self.pos < self.src.len() && self.peek_cp() != q {
                if self.peek_cp() == 92 { self.advance(); }
                self.advance();
            }
            let text = self.slice(start, self.pos);
            self.advance();
            return Token { kind: TokKind::Str, text, line, col };
        }
        // operators: longest match first
        let two = self.slice(self.pos, (self.pos + 2).min(self.src.len()));
        let three = if self.pos + 2 < self.src.len() {
            self.slice(self.pos, self.pos + 3)
        } else {
            two.clone()
        };
        if three == "//=" || three == "**=" {
            self.advance();
            self.advance();
            self.advance();
            return Token { kind: TokKind::Op, text: three, line, col };
        }
        const TWO_OPS: &[&str] = &[
            "//", "**", "<<", ">>", "<=", ">=", "==", "!=", "+=", "-=",
            "*=", "/=", "%=", "->", ":=", "|=", "&=", "^=",
        ];
        if TWO_OPS.contains(&two.as_str()) {
            self.advance();
            self.advance();
            return Token { kind: TokKind::Op, text: two, line, col };
        }
        self.advance();
        if c == 40 || c == 91 || c == 123 {
            self.depth += 1;
        } else if c == 41 || c == 93 || c == 125 {
            self.depth -= 1;
        }
        let text = self.slice(self.pos - 1, self.pos);
        Token { kind: TokKind::Op, text, line, col }
    }
}

fn tokenize(src: &str) -> Vec<Token> {
    let mut lexer = Lexer::new(src);
    let mut toks = Vec::new();
    loop {
        let t = lexer.next_token();
        let end = t.kind == TokKind::End;
        toks.push(t);
        if end { return toks; }
    }
}

// ---------- escapes and numeric literal conversion ----------

fn hex_val(ch: char) -> i64 {
    let o = ch as i64;
    if (48..=57).contains(&o) { return o - 48; }
    if (97..=102).contains(&o) { return o - 87; }
    if (65..=70).contains(&o) { return o - 55; }
    -1
}

fn unescape(s: &str) -> String {
    // Python-compatible escape decoding, mirroring silu_fe.unescape
    let src: Vec<char> = s.chars().collect();
    let mut out = String::new();
    let n = src.len();
    let mut i = 0usize;
    while i < n {
        let ch = src[i];
        if ch == '\\' && i + 1 < n {
            let nxt = src[i + 1];
            match nxt {
                'n' => { out.push('\n'); i += 2; }
                't' => { out.push('\t'); i += 2; }
                'r' => { out.push('\r'); i += 2; }
                '"' => { out.push('"'); i += 2; }
                '\'' => { out.push('\''); i += 2; }
                '\\' => { out.push('\\'); i += 2; }
                'a' => { out.push('\x07'); i += 2; }
                'b' => { out.push('\x08'); i += 2; }
                'f' => { out.push('\x0c'); i += 2; }
                'v' => { out.push('\x0b'); i += 2; }
                'x' => {
                    if i + 3 < n && hex_val(src[i + 2]) >= 0 && hex_val(src[i + 3]) >= 0 {
                        let v = hex_val(src[i + 2]) * 16 + hex_val(src[i + 3]);
                        out.push(char::from_u32(v as u32).unwrap_or('\u{fffd}'));
                        i += 4;
                    } else {
                        out.push(ch);
                        i += 1;
                    }
                }
                'u' => {
                    let mut ok4 = true;
                    let mut val4: i64 = 0;
                    let mut j4 = 2usize;
                    while j4 < 6 {
                        if i + j4 >= n || hex_val(src[i + j4]) < 0 {
                            ok4 = false;
                            break;
                        }
                        val4 = val4 * 16 + hex_val(src[i + j4]);
                        j4 += 1;
                    }
                    if ok4 {
                        out.push(char::from_u32(val4 as u32).unwrap_or('\u{fffd}'));
                        i += 6;
                    } else {
                        out.push(ch);
                        i += 1;
                    }
                }
                _ => {
                    let o8 = nxt as i64;
                    if (48..=55).contains(&o8) {
                        let mut val8 = o8 - 48;
                        let mut cnt8 = 1usize;
                        while cnt8 < 3 && i + cnt8 + 1 < n {
                            let d8 = src[i + cnt8 + 1] as i64;
                            if (48..=55).contains(&d8) {
                                val8 = val8 * 8 + (d8 - 48);
                                cnt8 += 1;
                            } else { break; }
                        }
                        if val8 < 256 {
                            out.push(char::from_u32(val8 as u32).unwrap_or('\u{fffd}'));
                            i += cnt8 + 1;
                        } else {
                            out.push(ch);
                            i += 1;
                        }
                    } else {
                        out.push(ch);
                        i += 1;
                    }
                }
            }
        } else {
            out.push(ch);
            i += 1;
        }
    }
    out
}

fn strip_uscores(t: &str) -> String {
    t.chars().filter(|c| *c != '_').collect()
}

fn to_float(text: &str) -> f64 {
    let t = strip_uscores(text);
    // the spec's float() is the C strtod underneath silu's runtime,
    // which ACCEPTS hex ("0xE0" -> 224.0); rust's parse does not
    if t.len() > 2 {
        let b = t.as_bytes();
        if b[0] == b'0' && (b[1] == b'x' || b[1] == b'X') {
            if let Ok(v) = i64::from_str_radix(&t[2..], 16) {
                return v as f64;
            }
        }
    }
    if let Ok(v) = t.parse::<f64>() { return v; }
    // python accepts "1." / "1.e5"; rust's parser does not always
    if let Some(stripped) = t.strip_suffix('.') {
        if let Ok(v) = format!("{}0", stripped).parse::<f64>() { return v; }
    }
    if let Some(pos) = t.rfind('.') {
        // "1.e5" -> "1.0e5"
        let fixed = format!("{}.0{}", &t[..pos + 1], &t[pos + 1..]);
        if let Ok(v) = fixed.parse::<f64>() { return v; }
    }
    0.0
}

fn to_int(text: &str) -> i64 {
    let t = strip_uscores(text);
    if t.contains('.') || t.contains('e') || t.contains('E') {
        return to_float(&t) as i64;
    }
    if t.len() > 1 && t.starts_with('0') {
        let c = t.as_bytes()[1] as char;
        if c == 'x' || c == 'X' {
            return i64::from_str_radix(&t[2..], 16).unwrap_or(0);
        }
        if c == 'b' || c == 'B' {
            return i64::from_str_radix(&t[2..], 2).unwrap_or(0);
        }
        if c == 'o' || c == 'O' {
            return i64::from_str_radix(&t[2..], 8).unwrap_or(0);
        }
    }
    t.parse::<i64>().unwrap_or(0)
}

fn const_num(tok: &Token) -> Val {
    let t = &tok.text;
    let b = t.as_bytes();
    if b.len() >= 2 && b[0] == b'0' {
        let c = b[1] as char;
        if c == 'x' || c == 'X' || c == 'b' || c == 'B' || c == 'o' || c == 'O' {
            return ns2("const", Val::i(to_int(t)));
        }
    }
    if t.contains('.') || t.contains('e') || t.contains('E') {
        return ns2("const", Val::f(to_float(t)));
    }
    ns2("const", Val::i(to_int(t)))
}

fn fe_const_str(tok: &Token) -> Val {
    ns2("const", Val::s(&unescape(&tok.text)))
}

fn const_bytes(tok: &Token) -> Val {
    ns2("const_b", Val::s(&unescape(&tok.text)))
}

fn fe_error(msg: &str, tok: &Token) -> ! {
    eprintln!("silu-fe error line {}: {}", tok.line, msg);
    std::process::exit(1);
}

// ---------- parser ----------

struct Parser { toks: Vec<Token>, pos: usize }

impl Parser {
    fn cur(&self) -> Token { self.toks[self.pos].clone() }
    fn nxt(&mut self) -> Token {
        let t = self.toks[self.pos].clone();
        self.pos += 1;
        t
    }
    fn accept(&mut self, text: &str) -> bool {
        let t = self.cur();
        if (t.kind == TokKind::Op || t.kind == TokKind::Kw) && t.text == text {
            self.pos += 1;
            return true;
        }
        false
    }
    fn expect(&mut self, text: &str) -> Token {
        let t = self.cur();
        if (t.kind != TokKind::Op && t.kind != TokKind::Kw) || t.text != text {
            fe_error(&format!("expected '{}', got '{}'", text, t.text), &t);
        }
        self.nxt()
    }
    fn expect_kind(&mut self, kind: TokKind) -> Token {
        let t = self.cur();
        if t.kind != kind {
            fe_error("expected token kind", &t);
        }
        self.nxt()
    }
    fn at_end(&self) -> bool { self.cur().kind == TokKind::End }

    fn parse_module(&mut self) -> Val {
        let mut stmts: Vec<Val> = Vec::new();
        while !self.at_end() {
            let t = self.cur();
            if t.kind == TokKind::Nl {
                self.nxt();
                continue;
            }
            let st = self.parse_stmt();
            if st.is_node() && st.head() == "export_stmt" {
                stmts.push(ns2("line", st.get(1)));
                stmts.push(st.get(2));
            } else {
                stmts.push(ns2("line", Val::i(t.line)));
                stmts.push(st);
            }
        }
        ns2("module", Val::List(stmts))
    }

    fn parse_stmt(&mut self) -> Val {
        let t = self.cur();
        if t.kind == TokKind::Name && t.text == "match" && self.stmt_ends_with_colon() {
            return self.parse_match();
        }
        if t.kind == TokKind::Op && t.text == "@" {
            self.nxt();
            let dn = self.expect_kind(TokKind::Name).text;
            if dn != "export" {
                fe_error("only @export is supported", &t);
            }
            self.expect_nl();
            let nd = self.cur();
            if !(nd.kind == TokKind::Kw && nd.text == "def") {
                fe_error("@export must decorate a def", &nd);
            }
            let fdef = self.parse_func_def(true);
            return Val::node("export_stmt", vec![Val::i(nd.line), fdef]);
        }
        if t.kind == TokKind::Kw {
            match t.text.as_str() {
                "def" => return self.parse_func_def(false),
                "class" => return self.parse_class_def(),
                "if" => return self.parse_if(),
                "while" => return self.parse_while(),
                "for" => return self.parse_for(),
                "return" => return self.parse_return(),
                "break" => {
                    self.nxt();
                    self.expect_nl();
                    return n0("break");
                }
                "continue" => {
                    self.nxt();
                    self.expect_nl();
                    return n0("continue");
                }
                "pass" => {
                    self.nxt();
                    self.expect_nl();
                    return n0("pass");
                }
                "import" | "from" => return self.parse_import(),
                "raise" => return self.parse_raise(),
                "del" => return self.parse_del(),
                "assert" => return self.parse_assert(),
                _ => {}
            }
        }
        self.parse_simple_stmt()
    }

    fn expect_nl(&mut self) {
        let t = self.cur();
        if t.kind == TokKind::Nl {
            self.nxt();
        } else if t.kind != TokKind::End {
            fe_error("expected end of line", &t);
        }
    }

    fn parse_import(&mut self) -> Val {
        if self.cur().text == "from" {
            self.nxt();
            let mut level = 0;
            while self.accept(".") {
                level += 1;
            }
            let mut mod_text = String::new();
            let mut has_module = false;
            if self.cur().kind == TokKind::Name {
                mod_text = self.expect_kind(TokKind::Name).text;
                while self.accept(".") {
                    mod_text = format!("{}.{}", mod_text, self.expect_kind(TokKind::Name).text);
                }
                has_module = true;
            }
            if has_module && mod_text == "c" && level == 0 {
                self.expect("import");
                let mut pairs_c: Vec<Val> = Vec::new();
                loop {
                    let cn = self.expect_kind(TokKind::Name).text;
                    let mut ca = cn.clone();
                    if self.accept("as") {
                        ca = self.expect_kind(TokKind::Name).text;
                    }
                    pairs_c.push(Val::List(vec![Val::s(&cn), Val::s(&ca)]));
                    if !self.accept(",") { break; }
                }
                self.expect_nl();
                return ns2("c_extern", Val::List(pairs_c));
            }
            self.expect("import");
            let mut pairs: Vec<Val> = Vec::new();
            loop {
                let nm = self.expect_kind(TokKind::Name).text;
                let asn = if self.accept("as") {
                    Val::s(&self.expect_kind(TokKind::Name).text)
                } else {
                    Val::Null
                };
                pairs.push(Val::List(vec![Val::s(&nm), asn]));
                if !self.accept(",") { break; }
            }
            self.expect_nl();
            if has_module {
                return Val::node("from_import",
                                 vec![Val::s(&mod_text), Val::List(pairs), Val::i(level)]);
            }
            return Val::node("from_import",
                             vec![Val::Null, Val::List(pairs), Val::i(level)]);
        }
        self.expect("import");
        let mut pairs: Vec<Val> = Vec::new();
        loop {
            let mut nm = self.expect_kind(TokKind::Name).text;
            while self.accept(".") {
                nm = format!("{}.{}", nm, self.expect_kind(TokKind::Name).text);
            }
            let asn = if self.accept("as") {
                Val::s(&self.expect_kind(TokKind::Name).text)
            } else {
                Val::Null
            };
            pairs.push(Val::List(vec![Val::s(&nm), asn]));
            if !self.accept(",") { break; }
        }
        self.expect_nl();
        ns2("import", Val::List(pairs))
    }

    fn parse_func_def(&mut self, exported: bool) -> Val {
        self.expect("def");
        let name = self.expect_kind(TokKind::Name).text;
        self.expect("(");
        let mut params: Vec<Val> = Vec::new();
        let mut annos: Vec<Val> = Vec::new();
        while !(self.cur().kind == TokKind::Op && self.cur().text == ")") {
            let pname = self.expect_kind(TokKind::Name).text;
            params.push(Val::s(&pname));
            annos.push(Val::Null);
            if self.accept(":") {
                let a = self.parse_annotation();
                annos.pop();
                annos.push(a);
            }
            if !self.accept(",") { break; }
        }
        self.expect(")");
        let mut ret_anno = Val::Null;
        if self.accept("->") {
            ret_anno = self.parse_annotation();
        }
        self.expect(":");
        let body = self.parse_block();
        if exported {
            return Val::node("func_def", vec![Val::s(&name), Val::List(params), body,
                                              Val::List(annos), ret_anno, Val::s("export")]);
        }
        Val::node("func_def", vec![Val::s(&name), Val::List(params), body,
                                   Val::List(annos), ret_anno])
    }

    fn parse_annotation(&mut self) -> Val {
        let t = self.cur();
        if t.kind == TokKind::Kw && t.text == "None" {
            self.nxt();
            return ns2("const", Val::Null);
        }
        let name = self.expect_kind(TokKind::Name).text;
        if self.accept("[") {
            let mut inner = vec![self.parse_annotation()];
            while self.accept(",") {
                inner.push(self.parse_annotation());
            }
            self.expect("]");
            let inner_val = if inner.len() == 1 {
                inner.pop().unwrap()
            } else {
                ns2("tuple", Val::List(inner))
            };
            return Val::node("subscript", vec![ns2("name", Val::s(&name)), inner_val]);
        }
        ns2("name", Val::s(&name))
    }

    fn parse_class_def(&mut self) -> Val {
        self.expect("class");
        let name = self.expect_kind(TokKind::Name).text;
        let mut bases: Vec<String> = Vec::new();
        if self.accept("(") {
            while !(self.cur().kind == TokKind::Op && self.cur().text == ")") {
                bases.push(self.expect_kind(TokKind::Name).text);
                if !self.accept(",") { break; }
            }
            self.expect(")");
        }
        self.expect(":");
        let body = self.parse_block();
        if bases.len() == 1 && bases[0] == "Enum" {
            let mut members: Vec<Val> = Vec::new();
            for stmt in body_list(&body) {
                if stmt.head() == "line" {
                    continue;
                }
                if stmt.head() == "assign" && stmt.get(1).str_or().is_some() {
                    members.push(Val::List(vec![stmt.get(1), stmt.get(2)]));
                } else if stmt.head() == "name" {
                    members.push(Val::List(vec![stmt.get(1), Val::Null]));
                }
            }
            return Val::node("enum_def", vec![Val::s(&name), Val::List(members)]);
        }
        if !bases.is_empty() {
            let t = self.cur();
            fe_error("inheritance not supported", &t);
        }
        Val::node("class_def", vec![Val::s(&name), Val::List(vec![]), body])
    }

    fn parse_block(&mut self) -> Val {
        self.expect_nl();
        let mut stmts: Vec<Val> = Vec::new();
        let mut base_col: Option<i64> = None;
        while !self.at_end() {
            let t = self.cur();
            if t.kind == TokKind::Nl {
                self.nxt();
                continue;
            }
            if base_col.is_none() {
                base_col = Some(t.col);
            }
            if t.col < base_col.unwrap() {
                break;
            }
            let st = self.parse_stmt();
            if st.is_node() && st.head() == "export_stmt" {
                stmts.push(ns2("line", st.get(1)));
                stmts.push(st.get(2));
            } else {
                stmts.push(ns2("line", Val::i(t.line)));
                stmts.push(st);
            }
        }
        Val::List(stmts)
    }

    fn parse_if(&mut self) -> Val {
        let if_col = self.cur().col;
        self.expect("if");
        let test = self.parse_expr_nt();
        self.expect(":");
        let body = self.parse_block();
        let mut orelse = Val::List(vec![]);
        let t = self.cur();
        if t.kind == TokKind::Kw && t.text == "elif" && t.col == if_col {
            let arm_line = t.line;
            self.nxt();
            let inner = self.parse_if_tail(if_col);
            orelse = Val::List(vec![ns2("line", Val::i(arm_line)), inner]);
        } else if t.kind == TokKind::Kw && t.text == "else" && t.col == if_col {
            self.nxt();
            self.expect(":");
            orelse = self.parse_block();
        }
        Val::node("if", vec![test, body, orelse])
    }

    fn parse_if_tail(&mut self, if_col: i64) -> Val {
        let test = self.parse_expr_nt();
        self.expect(":");
        let body = self.parse_block();
        let mut orelse = Val::List(vec![]);
        let t = self.cur();
        if t.kind == TokKind::Kw && t.text == "elif" && t.col == if_col {
            let arm_line = t.line;
            self.nxt();
            let inner = self.parse_if_tail(if_col);
            orelse = Val::List(vec![ns2("line", Val::i(arm_line)), inner]);
        } else if t.kind == TokKind::Kw && t.text == "else" && t.col == if_col {
            self.nxt();
            self.expect(":");
            orelse = self.parse_block();
        }
        Val::node("if", vec![test, body, orelse])
    }

    fn parse_while(&mut self) -> Val {
        self.expect("while");
        let test = self.parse_expr_nt();
        self.expect(":");
        let body = self.parse_block();
        Val::node("while", vec![test, body])
    }

    fn parse_for(&mut self) -> Val {
        self.expect("for");
        let first = self.expect_kind(TokKind::Name).text;
        let mut target = ns2("name", Val::s(&first));
        if self.cur().kind == TokKind::Op && self.cur().text == "," {
            let mut names = vec![Val::s(&first)];
            while self.cur().kind == TokKind::Op && self.cur().text == "," {
                self.nxt();
                names.push(Val::s(&self.expect_kind(TokKind::Name).text));
            }
            target = ns2("tuple_unpack", Val::List(names));
        }
        self.expect("in");
        let iter_expr = self.parse_expr();
        self.expect(":");
        let body = self.parse_block();
        Val::node("for", vec![target, iter_expr, body, Val::List(vec![])])
    }

    fn stmt_ends_with_colon(&self) -> bool {
        let mut i = self.pos;
        let mut last = self.toks[self.pos].clone();
        while i < self.toks.len() {
            let tk = &self.toks[i];
            if tk.kind == TokKind::Nl || tk.kind == TokKind::End {
                break;
            }
            last = tk.clone();
            i += 1;
        }
        last.kind == TokKind::Op && last.text == ":"
    }

    fn parse_match(&mut self) -> Val {
        let t0 = self.cur();
        if !(t0.kind == TokKind::Name && t0.text == "match") {
            fe_error("expected 'match'", &t0);
        }
        self.nxt();
        let subject = self.parse_expr_nt();
        self.expect(":");
        self.expect_nl();
        let mut cases: Vec<Val> = Vec::new();
        let mut base_col: Option<i64> = None;
        while !self.at_end() {
            let t = self.cur();
            if t.kind == TokKind::Nl {
                self.nxt();
                continue;
            }
            if t.kind != TokKind::Name || t.text != "case" {
                break;
            }
            if base_col.is_none() {
                base_col = Some(t.col);
            }
            if t.col < base_col.unwrap() {
                break;
            }
            self.nxt();
            let pattern = self.parse_pattern();
            let mut guard = Val::Null;
            if self.accept("if") {
                guard = self.parse_expr_nt();
            }
            self.expect(":");
            let body = self.parse_block();
            cases.push(Val::node("match_case", vec![pattern, guard, body]));
        }
        Val::node("match", vec![subject, Val::List(cases)])
    }

    fn parse_fstring(&mut self, raw: &str) -> Val {
        let raw_chars: Vec<char> = raw.chars().collect();
        let mut parts: Vec<Val> = Vec::new();
        let mut lit = String::new();
        let n = raw_chars.len();
        let mut i = 0usize;
        while i < n {
            let ch = raw_chars[i];
            if ch == '{' && i + 1 < n && raw_chars[i + 1] == '{' {
                lit.push('{');
                i += 2;
            } else if ch == '}' && i + 1 < n && raw_chars[i + 1] == '}' {
                lit.push('}');
                i += 2;
            } else if ch == '{' {
                if !lit.is_empty() {
                    parts.push(ns2("const", Val::s(&unescape(&lit))));
                    lit.clear();
                }
                let mut j = i + 1;
                while j < n && raw_chars[j] != '}' {
                    j += 1;
                }
                let expr_src: String = raw_chars[i + 1..j].iter().collect();
                let mut sub_parser = Parser::new(tokenize(&expr_src));
                parts.push(sub_parser.parse_expr());
                i = j + 1;
            } else {
                lit.push(ch);
                i += 1;
            }
        }
        if !lit.is_empty() {
            parts.push(ns2("const", Val::s(&unescape(&lit))));
        }
        if parts.is_empty() {
            return ns2("const", Val::s(""));
        }
        Val::node("call", vec![ns2("name", Val::s("fmt")), Val::List(parts), Val::List(vec![])])
    }

    fn parse_pattern(&mut self) -> Val {
        let t = self.cur();
        if t.kind == TokKind::Name && t.text == "_" {
            self.nxt();
            return Val::node("match_as", vec![Val::Null, Val::Null]);
        }
        if t.kind == TokKind::Num {
            self.nxt();
            return ns2("match_value", const_num(&t));
        }
        if t.kind == TokKind::Str {
            self.nxt();
            return ns2("match_value", fe_const_str(&t));
        }
        if t.kind == TokKind::Name {
            self.nxt();
            if self.cur().kind == TokKind::Op && self.cur().text == "." {
                self.nxt();
                let member = self.expect_kind(TokKind::Name).text;
                return ns2("match_value",
                           Val::node("attribute", vec![ns2("name", Val::s(&t.text)),
                                                        Val::s(&member)]));
            }
            if self.cur().kind == TokKind::Op && self.cur().text == "(" {
                self.nxt();
                let mut pats: Vec<Val> = Vec::new();
                let mut kattrs: Vec<Val> = Vec::new();
                let mut kpats: Vec<Val> = Vec::new();
                while !(self.cur().kind == TokKind::Op && self.cur().text == ")") {
                    if self.cur().kind == TokKind::Name
                        && self.toks[self.pos + 1].kind == TokKind::Op
                        && self.toks[self.pos + 1].text == "="
                    {
                        let kn = self.nxt().text;
                        self.nxt();
                        kattrs.push(Val::s(&kn));
                        kpats.push(self.parse_pattern());
                    } else {
                        pats.push(self.parse_pattern());
                    }
                    if !self.accept(",") { break; }
                }
                self.expect(")");
                return Val::node("match_class",
                                 vec![ns2("name", Val::s(&t.text)), Val::List(pats),
                                      Val::List(kattrs), Val::List(kpats)]);
            }
            return Val::node("match_as", vec![Val::Null, Val::s(&t.text)]);
        }
        fe_error("unsupported pattern", &t)
    }

    fn parse_return(&mut self) -> Val {
        self.expect("return");
        if self.cur().kind == TokKind::Nl {
            self.expect_nl();
            return ns2("return", Val::Null);
        }
        let value = self.parse_expr();
        self.expect_nl();
        ns2("return", value)
    }

    fn parse_raise(&mut self) -> Val {
        self.expect("raise");
        let value = self.parse_expr();
        self.expect_nl();
        ns2("raise", value)
    }

    fn parse_del(&mut self) -> Val {
        self.expect("del");
        let target = self.parse_expr();
        self.expect_nl();
        if target.is_node() && target.head() == "subscript" {
            return Val::node("delete", vec![target.get(1), target.get(2)]);
        }
        ns2("delete", target)
    }

    fn parse_assert(&mut self) -> Val {
        self.expect("assert");
        let test = self.parse_expr_nt();
        let mut msg = Val::Null;
        if self.accept(",") {
            msg = self.parse_expr_nt();
        }
        self.expect_nl();
        Val::node("assert", vec![test, msg])
    }

    fn parse_simple_stmt(&mut self) -> Val {
        let t = self.cur();
        if t.kind == TokKind::Name
            && self.toks[self.pos + 1].kind == TokKind::Op
            && self.toks[self.pos + 1].text == ":"
            && t.text != "match"
            && t.text != "case"
        {
            let name = self.nxt().text;
            self.nxt(); // ':'
            let anno = self.parse_annotation();
            let mut value = Val::Null;
            if self.accept("=") {
                value = self.parse_expr();
            }
            self.expect_nl();
            return Val::node("ann_assign", vec![Val::s(&name), value, anno]);
        }
        let expr = self.parse_expr();
        let t = self.cur();
        let assign_ops = ["=", "+=", "-=", "*=", "/=", "//=", "%="];
        if t.kind == TokKind::Op && assign_ops.contains(&t.text.as_str()) {
            self.nxt();
            let mut value = self.parse_expr();
            let mut chained = false;
            let mut chain_targets: Vec<Val> = Vec::new();
            while self.cur().kind == TokKind::Op
                && self.cur().text == "="
                && value.is_node()
                && value.head() == "name"
            {
                if !chained {
                    chained = true;
                    chain_targets = vec![expr.clone(), value.clone()];
                } else {
                    chain_targets.push(value.clone());
                }
                self.nxt();
                value = self.parse_expr();
                if !(value.is_node() && value.head() == "name") {
                    break;
                }
            }
            if chained {
                let mut stmts: Vec<Val> = Vec::new();
                for ct in &chain_targets {
                    stmts.push(Val::node("assign", vec![ct.get(1), value.clone(), Val::Null]));
                }
                self.expect_nl();
                return ns2("multi_assign", Val::List(stmts));
            }
            self.expect_nl();
            let op: Option<&str> = match t.text.as_str() {
                "=" => None,
                "+=" => Some("+"),
                "-=" => Some("-"),
                "*=" => Some("*"),
                "/=" => Some("/"),
                "//=" => Some("//"),
                "%=" => Some("%"),
                _ => None,
            };
            let _ = op;
            let target = expr;
            let head = target.head().to_string();
            if head == "name" {
                if t.text == "=" {
                    return Val::node("assign", vec![target.get(1), value, Val::Null]);
                }
                return Val::node("aug_assign", vec![target, Val::s(&t.text), value]);
            }
            if head == "subscript" {
                if t.text == "=" {
                    return Val::node("subscript_assign",
                                     vec![target.get(1), target.get(2), value]);
                }
                return Val::node("aug_assign", vec![target, Val::s(&t.text), value]);
            }
            if head == "attribute" {
                if t.text == "=" {
                    return Val::node("assign", vec![target, value, Val::Null]);
                }
                return Val::node("attribute_aug_assign",
                                 vec![target.get(1), target.get(2), Val::s(&t.text), value]);
            }
            if head == "tuple" {
                let items = body_list(&target.get(1));
                let names: Vec<Val> = items.iter()
                    .filter(|it| it.is_node() && it.head() == "name")
                    .map(|it| it.get(1))
                    .collect();
                return Val::node("tuple_assign", vec![Val::List(names), value]);
            }
            fe_error("unsupported assignment target", &t);
        }
        self.expect_nl();
        expr
    }

    fn parse_expr(&mut self) -> Val {
        let value = self.parse_expr_nt();
        let t = self.cur();
        if t.kind == TokKind::Op && t.text == "," {
            let mut items = vec![value];
            while self.accept(",") {
                let t2 = self.cur();
                if t2.kind == TokKind::Nl || t2.kind == TokKind::End {
                    break;
                }
                if t2.kind == TokKind::Op && t2.text == "=" {
                    break;
                }
                items.push(self.parse_expr_nt());
            }
            return ns2("tuple", Val::List(items));
        }
        value
    }

    fn parse_expr_nt(&mut self) -> Val {
        let value = self.parse_or();
        let t = self.cur();
        if t.kind == TokKind::Kw && t.text == "if" {
            self.nxt();
            let cond = self.parse_or();
            let t2 = self.cur();
            if !(t2.kind == TokKind::Kw && t2.text == "else") {
                fe_error("expected 'else' in conditional expression", &t2);
            }
            self.nxt();
            let else_val = self.parse_expr_nt();
            return Val::node("if_expr", vec![cond, value, else_val]);
        }
        value
    }

    fn parse_or(&mut self) -> Val {
        let left = self.parse_and();
        let mut parts = vec![left.clone()];
        while self.accept("or") {
            parts.push(self.parse_and());
        }
        if parts.len() == 1 {
            return left;
        }
        Val::node("or", parts)
    }

    fn parse_and(&mut self) -> Val {
        let left = self.parse_not();
        let mut parts = vec![left.clone()];
        while self.accept("and") {
            parts.push(self.parse_not());
        }
        if parts.len() == 1 {
            return left;
        }
        Val::node("and", parts)
    }

    fn parse_not(&mut self) -> Val {
        if self.accept("not") {
            return ns2("not", self.parse_not());
        }
        self.parse_compare()
    }

    fn parse_compare(&mut self) -> Val {
        let left = self.parse_bitor();
        let t = self.cur();
        let cmp_ops = ["==", "!=", "<", "<=", ">", ">="];
        if t.kind == TokKind::Op && cmp_ops.contains(&t.text.as_str()) {
            self.nxt();
            let mut right = self.parse_bitor();
            let t2 = self.cur();
            if t2.kind == TokKind::Op && cmp_ops.contains(&t2.text.as_str()) {
                let mut pairs = vec![Val::List(vec![Val::s(&t.text), left.clone(), right.clone()])];
                loop {
                    let t3 = self.cur();
                    if t3.kind == TokKind::Op && cmp_ops.contains(&t3.text.as_str()) {
                        self.nxt();
                        let nxt2 = self.parse_bitor();
                        pairs.push(Val::List(vec![Val::s(&t3.text), right.clone(), nxt2.clone()]));
                        right = nxt2;
                    } else {
                        break;
                    }
                }
                return ns2("chained_compare", Val::List(pairs));
            }
            return Val::node(&t.text, vec![left, right]);
        }
        if t.kind == TokKind::Kw && t.text == "is" {
            self.nxt();
            if self.accept("not") {
                return Val::node("is not", vec![left, self.parse_bitor()]);
            }
            return Val::node("is", vec![left, self.parse_bitor()]);
        }
        if t.kind == TokKind::Kw && t.text == "in" {
            self.nxt();
            let right = self.parse_bitor();
            return Val::node("in", vec![left, right]);
        }
        if t.kind == TokKind::Kw && t.text == "not" {
            self.nxt();
            self.expect("in");
            return Val::node("not in", vec![left, self.parse_bitor()]);
        }
        left
    }

    fn parse_bitor(&mut self) -> Val {
        let mut left = self.parse_bitxor();
        while self.accept("|") {
            left = Val::node("|", vec![left, self.parse_bitxor()]);
        }
        left
    }

    fn parse_bitxor(&mut self) -> Val {
        let mut left = self.parse_bitand();
        while self.accept("^") {
            left = Val::node("^", vec![left, self.parse_bitand()]);
        }
        left
    }

    fn parse_bitand(&mut self) -> Val {
        let mut left = self.parse_shift();
        while self.accept("&") {
            left = Val::node("&", vec![left, self.parse_shift()]);
        }
        left
    }

    fn parse_shift(&mut self) -> Val {
        let mut left = self.parse_add();
        while self.cur().kind == TokKind::Op
            && (self.cur().text == "<<" || self.cur().text == ">>")
        {
            let op = self.nxt().text;
            left = Val::node(&op, vec![left, self.parse_add()]);
        }
        left
    }

    fn parse_add(&mut self) -> Val {
        let mut left = self.parse_mul();
        while self.cur().kind == TokKind::Op
            && (self.cur().text == "+" || self.cur().text == "-")
        {
            let op = self.nxt().text;
            left = Val::node(&op, vec![left, self.parse_mul()]);
        }
        left
    }

    fn parse_mul(&mut self) -> Val {
        let mut left = self.parse_pow();
        while self.cur().kind == TokKind::Op
            && ["*", "/", "//", "%"].contains(&self.cur().text.as_str())
        {
            let op = self.nxt().text;
            left = Val::node(&op, vec![left, self.parse_pow()]);
        }
        left
    }

    fn parse_pow(&mut self) -> Val {
        let base = self.parse_unary();
        if self.accept("**") {
            return Val::node("**", vec![base, self.parse_pow()]);
        }
        base
    }

    fn parse_unary(&mut self) -> Val {
        let t = self.cur();
        if t.kind == TokKind::Op && t.text == "-" {
            if self.toks[self.pos + 1].kind == TokKind::Num
                && self.toks[self.pos + 1].text == "9223372036854775808"
            {
                self.nxt();
                self.nxt();
                return ns2("const", Val::i(to_int("-9223372036854775808")));
            }
            self.nxt();
            return ns2("-", self.parse_unary());
        }
        if t.kind == TokKind::Op && t.text == "+" {
            self.nxt();
            return ns2("+", self.parse_unary());
        }
        if t.kind == TokKind::Op && t.text == "~" {
            self.nxt();
            return ns2("~", self.parse_unary());
        }
        self.parse_postfix()
    }

    fn parse_postfix(&mut self) -> Val {
        let mut node = self.parse_atom();
        loop {
            if self.accept("(") {
                let mut args: Vec<Val> = Vec::new();
                let mut kwargs: Vec<Val> = Vec::new();
                while !(self.cur().kind == TokKind::Op && self.cur().text == ")") {
                    if self.cur().kind == TokKind::Name
                        && self.toks[self.pos + 1].text == "="
                    {
                        let k = self.nxt().text;
                        self.expect("=");
                        kwargs.push(Val::List(vec![Val::s(&k), self.parse_expr_nt()]));
                    } else {
                        args.push(self.parse_expr_nt());
                    }
                    if !self.accept(",") { break; }
                }
                self.expect(")");
                node = Val::node("call", vec![node, Val::List(args), Val::List(kwargs)]);
            } else if self.accept("[") {
                if self.accept(":") {
                    let lo = Val::Null;
                    let mut hi = Val::Null;
                    let mut step = Val::Null;
                    if self.cur().text != ":" && self.cur().text != "]" {
                        hi = self.parse_expr_nt();
                    }
                    if self.accept(":")
                        && self.cur().text != "]" {
                            step = self.parse_expr_nt();
                        }
                    self.expect("]");
                    node = Val::node("subscript",
                                     vec![node, Val::node("slice", vec![lo, hi, step])]);
                } else {
                    let mut index = self.parse_expr_nt();
                    if self.cur().kind == TokKind::Op && self.cur().text == "," {
                        let mut kitems = vec![index];
                        while self.accept(",") {
                            if self.cur().text == "]" { break; }
                            kitems.push(self.parse_expr_nt());
                        }
                        index = ns2("tuple", Val::List(kitems));
                    }
                    if self.accept(":") {
                        let lo2 = index;
                        let mut hi2 = Val::Null;
                        let mut step2 = Val::Null;
                        if self.cur().text != ":" && self.cur().text != "]" {
                            hi2 = self.parse_expr_nt();
                        }
                        if self.accept(":")
                            && self.cur().text != "]" {
                                step2 = self.parse_expr_nt();
                            }
                        self.expect("]");
                        node = Val::node("subscript",
                                         vec![node, Val::node("slice", vec![lo2, hi2, step2])]);
                    } else {
                        self.expect("]");
                        node = ns3("subscript", node, index);
                    }
                }
            } else if self.accept(".") {
                let attr = self.expect_kind(TokKind::Name).text;
                node = ns3("attribute", node, Val::s(&attr));
            } else {
                return node;
            }
        }
    }

    fn parse_atom(&mut self) -> Val {
        let t = self.cur();
        if t.kind == TokKind::Num {
            self.nxt();
            return const_num(&t);
        }
        if t.kind == TokKind::Str {
            self.nxt();
            return fe_const_str(&t);
        }
        if t.kind == TokKind::Bytes {
            self.nxt();
            return const_bytes(&t);
        }
        if t.kind == TokKind::FStr {
            self.nxt();
            return self.parse_fstring(&t.text);
        }
        if t.kind == TokKind::Name {
            self.nxt();
            return ns2("name", Val::s(&t.text));
        }
        if t.kind == TokKind::Kw {
            match t.text.as_str() {
                "lambda" => {
                    self.nxt();
                    let mut lparams = vec![Val::s(&self.expect_kind(TokKind::Name).text)];
                    while self.cur().kind == TokKind::Op && self.cur().text == "," {
                        self.nxt();
                        lparams.push(Val::s(&self.expect_kind(TokKind::Name).text));
                    }
                    self.expect(":");
                    let lbody = self.parse_expr_nt();
                    return Val::node("lambda", vec![Val::List(lparams), lbody]);
                }
                "None" => {
                    self.nxt();
                    return ns2("const", Val::Null);
                }
                "True" => {
                    self.nxt();
                    return ns2("const", Val::Bool(true));
                }
                "False" => {
                    self.nxt();
                    return ns2("const", Val::Bool(false));
                }
                _ => {}
            }
        }
        if self.accept("(") {
            if self.accept(")") {
                return ns2("tuple", Val::List(vec![]));
            }
            let first = self.parse_expr_nt();
            if self.accept(",") {
                let mut items = vec![first];
                loop {
                    if self.cur().text == ")" { break; }
                    items.push(self.parse_expr_nt());
                    if !self.accept(",") { break; }
                }
                self.expect(")");
                return ns2("tuple", Val::List(items));
            }
            self.expect(")");
            return first;
        }
        if self.accept("[") {
            let mut items: Vec<Val> = Vec::new();
            if self.cur().text != "]" {
                items.push(self.parse_expr_nt());
                let t = self.cur();
                if t.kind == TokKind::Kw && t.text == "for" {
                    self.nxt();
                    let target = self.expect_kind(TokKind::Name).text;
                    self.expect("in");
                    let iter_expr = self.parse_or();
                    let mut conds: Vec<Val> = Vec::new();
                    loop {
                        let t2 = self.cur();
                        if t2.kind == TokKind::Kw && t2.text == "if" {
                            self.nxt();
                            conds.push(self.parse_or());
                        } else { break; }
                    }
                    self.expect("]");
                    return Val::node("list_comp", vec![
                        items[0].clone(),
                        Val::List(vec![Val::List(vec![
                            ns2("name", Val::s(&target)), iter_expr, Val::List(conds),
                        ])]),
                    ]);
                }
                while self.accept(",") {
                    if self.cur().text == "]" { break; }
                    items.push(self.parse_expr_nt());
                }
            }
            self.expect("]");
            return ns2("list", Val::List(items));
        }
        if self.accept("{") {
            if self.cur().text == "}" {
                self.nxt();
                return ns2("dict", Val::List(vec![]));
            }
            let k = self.parse_expr_nt();
            if self.cur().kind == TokKind::Op && self.cur().text == ":" {
                self.nxt();
                let v = self.parse_expr_nt();
                if self.cur().kind == TokKind::Kw && self.cur().text == "for" {
                    self.nxt();
                    let target = self.expect_kind(TokKind::Name).text;
                    self.expect("in");
                    let iter_expr = self.parse_or();
                    let mut conds: Vec<Val> = Vec::new();
                    loop {
                        let t3 = self.cur();
                        if t3.kind == TokKind::Kw && t3.text == "if" {
                            self.nxt();
                            conds.push(self.parse_or());
                        } else { break; }
                    }
                    self.expect("}");
                    return Val::node("dict_comp", vec![
                        Val::List(vec![k, v]),
                        Val::List(vec![Val::List(vec![
                            ns2("name", Val::s(&target)), iter_expr, Val::List(conds),
                        ])]),
                    ]);
                }
                let mut items = vec![Val::List(vec![k, v])];
                while self.accept(",") {
                    if self.cur().text == "}" { break; }
                    let k2 = self.parse_expr_nt();
                    self.expect(":");
                    let v2 = self.parse_expr_nt();
                    items.push(Val::List(vec![k2, v2]));
                }
                self.expect("}");
                return ns2("dict", Val::List(items));
            }
            if self.cur().kind == TokKind::Kw && self.cur().text == "for" {
                self.nxt();
                let target = self.expect_kind(TokKind::Name).text;
                self.expect("in");
                let iter_expr = self.parse_or();
                let mut conds: Vec<Val> = Vec::new();
                loop {
                    let t4 = self.cur();
                    if t4.kind == TokKind::Kw && t4.text == "if" {
                        self.nxt();
                        conds.push(self.parse_or());
                    } else { break; }
                }
                self.expect("}");
                return Val::node("set_comp", vec![
                    k,
                    Val::List(vec![Val::List(vec![
                        ns2("name", Val::s(&target)), iter_expr, Val::List(conds),
                    ])]),
                ]);
            }
            let mut items = vec![k];
            while self.accept(",") {
                if self.cur().text == "}" { break; }
                items.push(self.parse_expr_nt());
            }
            self.expect("}");
            return ns2("set", Val::List(items));
        }
        fe_error(&format!("unexpected token '{}'", t.text), &t)
    }
}

impl Parser {
    fn new(toks: Vec<Token>) -> Parser { Parser { toks, pos: 0 } }
}

// helper: children of a plain list value
fn body_list(v: &Val) -> Vec<Val> {
    match v { Val::List(items) => items.clone(), _ => vec![] }
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("usage: silu-fe <file.si>");
        std::process::exit(2);
    }
    let path = &args[1];
    let src = fs::read_to_string(path).unwrap_or_else(|e| {
        eprintln!("silu-fe: cannot read {}: {}", path, e);
        std::process::exit(1);
    });
    // imports resolve next to the source, like the self-hosted fe's cwd
    if let Some(parent) = Path::new(path).parent() {
        let _ = env::set_current_dir(parent);
    }
    let json = compile(&src);
    let stdout = std::io::stdout();
    let mut lock = stdout.lock();
    let _ = lock.write_all(json.as_bytes());
    let _ = lock.write_all(b"\n");
}

fn compile(src: &str) -> String {
    let mut parser = Parser::new(tokenize(src));
    let module = parser.parse_module();
    let mut alias_names: Vec<String> = Vec::new();
    let mut alias_exports: Vec<Rc<RefCell<Vec<String>>>> = Vec::new();
    let module = fe_expand_imports(module, &mut Vec::new(), &mut Vec::new(),
                                   &mut alias_names, &mut alias_exports);
    let module = fe_rewrite_aliases(&module, &alias_names, &alias_exports);
    let module = hoist_module(&module);
    json_dumps(&module)
}

// ---------- cross-file import expansion + nested-import hoisting ----------

type Exports = Vec<Rc<RefCell<Vec<String>>>>;

fn fe_drop_tail(xs: &[Val]) -> Vec<Val> {
    let n = xs.len();
    xs.iter().take(n.saturating_sub(1)).cloned().collect()
}

fn fe_collect_exports(stmts: &[Val]) -> Vec<String> {
    let mut out = Vec::new();
    for st in stmts {
        if st.is_node() {
            let op = st.head();
            if op == "func_def" || op == "class_def" {
                out.push(st.get(1).as_str());
            } else if op == "assign" || op == "ann_assign" {
                if let Some(name) = st.get(1).str_or() {
                    out.push(name);
                }
            }
        }
    }
    out
}

fn hg_in_list(names: &[String], name: &str) -> bool {
    names.iter().any(|n| n == name)
}

fn export_list_contains(exp: &Rc<RefCell<Vec<String>>>, name: &str) -> bool {
    exp.borrow().iter().any(|e| e == name)
}

fn fe_alias_index(names: &[String], name: &str) -> i64 {
    for (i, n) in names.iter().enumerate() {
        if n == name {
            return i as i64;
        }
    }
    -1
}

fn fe_register_alias(aname: &str, src_name: &str,
                     alias_names: &mut Vec<String>, alias_exports: &mut Exports) {
    let si = fe_alias_index(alias_names, src_name);
    if si < 0 { return; }
    let ti = fe_alias_index(alias_names, aname);
    if ti < 0 {
        alias_names.push(aname.to_string());
        alias_exports.push(alias_exports[si as usize].clone());
    } else {
        let additions: Vec<String> = alias_exports[si as usize].borrow()
            .iter().cloned().collect();
        for en in additions {
            if !export_list_contains(&alias_exports[ti as usize], &en) {
                alias_exports[ti as usize].borrow_mut().push(en);
            }
        }
    }
}

fn parse_file_module(path: &str) -> Val {
    let src = fs::read_to_string(path).unwrap_or_default();
    let mut parser = Parser::new(tokenize(&src));
    parser.parse_module()
}

fn fe_expand_imports(modv: Val, seen: &mut Vec<String>, stack: &mut Vec<String>,
                     alias_names: &mut Vec<String>, alias_exports: &mut Exports) -> Val {
    let stmts = body_list(&modv.get(1));
    let mut out: Vec<Val> = Vec::new();
    for st in &stmts {
        if st.is_node() && st.head() == "import" {
            let pairs = body_list(&st.get(1));
            let mut kept: Vec<Val> = Vec::new();
            let mut dropped = false;
            for pr in &pairs {
                let nm = pr.get(0).as_str();
                let path = format!("{}.si", nm);
                if Path::new(&path).exists() {
                    if !dropped {
                        dropped = true;
                        if !out.is_empty() {
                            let last = out.last().unwrap().clone();
                            if last.is_node() && last.head() == "line" {
                                out = fe_drop_tail(&out);
                            }
                        }
                    }
                    if stack.iter().any(|s| s == &path) {
                        eprintln!("M4 import error: import cycle through '{}'", path);
                        std::process::exit(1);
                    }
                    if !seen.iter().any(|s| s == &path) {
                        seen.push(path.clone());
                        stack.push(path.clone());
                        let sub_mod = parse_file_module(&path);
                        let sub_mod = fe_expand_imports(sub_mod, seen, stack,
                                                        alias_names, alias_exports);
                        stack.pop();
                        for sst in body_list(&sub_mod.get(1)) {
                            out.push(sst);
                        }
                        let sub_exports = fe_collect_exports(&body_list(&sub_mod.get(1)));
                        let ai = fe_alias_index(alias_names, &nm);
                        if ai < 0 {
                            alias_names.push(nm.clone());
                            alias_exports.push(Rc::new(RefCell::new(sub_exports)));
                        } else {
                            for en in sub_exports {
                                if !export_list_contains(&alias_exports[ai as usize], &en) {
                                    alias_exports[ai as usize].borrow_mut().push(en);
                                }
                            }
                        }
                    }
                    let asn = pr.get(1);
                    if !matches!(asn, Val::Null) && asn.as_str() != nm {
                        fe_register_alias(&asn.as_str(), &nm, alias_names, alias_exports);
                    }
                } else {
                    kept.push(pr.clone());
                }
            }
            if !kept.is_empty() {
                out.push(ns2("import", Val::List(kept)));
            }
        } else if st.is_node() && st.head() == "from_import" {
            let fmod = st.get(1);
            let flevel = st.get(3);
            let fmod_str = match &fmod { Val::Str(s) => s.clone(), _ => String::new() };
            let keep = matches!(fmod, Val::Null)
                || !matches!(flevel, Val::Int(0))
                || fmod_str.contains('.');
            if keep {
                out.push(st.clone());
                continue;
            }
            let fpath = format!("{}.si", fmod_str);
            if Path::new(&fpath).exists() {
                if !out.is_empty() {
                    let last = out.last().unwrap().clone();
                    if last.is_node() && last.head() == "line" {
                        out = fe_drop_tail(&out);
                    }
                }
                if stack.iter().any(|s| s == &fpath) {
                    eprintln!("M4 import error: import cycle through '{}'", fpath);
                    std::process::exit(1);
                }
                if !seen.iter().any(|s| s == &fpath) {
                    seen.push(fpath.clone());
                    stack.push(fpath.clone());
                    let fmod_ir = parse_file_module(&fpath);
                    let fmod_ir = fe_expand_imports(fmod_ir, seen, stack,
                                                    alias_names, alias_exports);
                    stack.pop();
                    for fst in body_list(&fmod_ir.get(1)) {
                        out.push(fst);
                    }
                    let fexports = fe_collect_exports(&body_list(&fmod_ir.get(1)));
                    let fai = fe_alias_index(alias_names, &fmod_str);
                    if fai < 0 {
                        alias_names.push(fmod_str.clone());
                        alias_exports.push(Rc::new(RefCell::new(fexports)));
                    } else {
                        for en2 in fexports {
                            if !export_list_contains(&alias_exports[fai as usize], &en2) {
                                alias_exports[fai as usize].borrow_mut().push(en2);
                            }
                        }
                    }
                }
            } else {
                out.push(st.clone());
            }
        } else {
            out.push(st.clone());
        }
    }
    let mod2 = ns2("module", Val::List(out));
    fe_hoist_nested(mod2, seen, stack, alias_names, alias_exports)
}

fn fe_load_splice(path: &str, nm: &str, seen: &mut Vec<String>, stack: &mut [String],
                  alias_names: &mut Vec<String>, alias_exports: &mut Exports) -> Vec<Val> {
    let mut stmts: Vec<Val> = Vec::new();
    if stack.iter().any(|s| s == path) {
        eprintln!("M4 import error: import cycle through '{}'", path);
        std::process::exit(1);
    }
    if !seen.iter().any(|s| s == path) {
        seen.push(path.to_string());
        let mut nstack = stack.to_vec();
        nstack.push(path.to_string());
        let mut sub = parse_file_module(path);
        sub = fe_expand_imports(sub, seen, &mut nstack, alias_names, alias_exports);
        for s in body_list(&sub.get(1)) {
            stmts.push(s);
        }
        let exports = fe_collect_exports(&body_list(&sub.get(1)));
        let ai = fe_alias_index(alias_names, nm);
        if ai < 0 {
            alias_names.push(nm.to_string());
            alias_exports.push(Rc::new(RefCell::new(exports)));
        } else {
            for en in exports {
                if !export_list_contains(&alias_exports[ai as usize], &en) {
                    alias_exports[ai as usize].borrow_mut().push(en);
                }
            }
        }
    }
    stmts
}

fn fe_collect_imports_list(stmts: &[Val], found: &mut Vec<Val>) {
    for st in stmts {
        if st.is_node() {
            let op = st.head();
            if op == "import" || op == "from_import" {
                found.push(st.clone());
            } else {
                fe_collect_imports_into(st, found);
            }
        }
    }
}

fn fe_collect_imports_into(st: &Val, found: &mut Vec<Val>) {
    if !st.is_node() { return; }
    let op = st.head();
    if op == "func_def" || op == "class_def" {
        fe_collect_imports_list(&body_list(&st.get(3)), found);
    } else if op == "if" {
        fe_collect_imports_list(&body_list(&st.get(2)), found);
        fe_collect_imports_list(&body_list(&st.get(3)), found);
    } else if op == "while" {
        fe_collect_imports_list(&body_list(&st.get(2)), found);
    } else if op == "for" {
        fe_collect_imports_list(&body_list(&st.get(3)), found);
    } else if op == "match" {
        for cs in body_list(&st.get(2)) {
            fe_collect_imports_list(&body_list(&cs.get(3)), found);
        }
    }
}

fn fe_node_in_list(xs: &[Val], node: &Val) -> bool {
    xs.iter().any(|x| x == node)
}

fn fe_subst_pass_list(stmts: &[Val], consumed: &[Val]) -> Vec<Val> {
    stmts.iter().map(|st| fe_subst_pass_stmt(st, consumed)).collect()
}

fn fe_subst_pass_stmt(st: &Val, consumed: &[Val]) -> Val {
    if !st.is_node() { return st.clone(); }
    let op = st.head();
    if op == "import" || op == "from_import" {
        if fe_node_in_list(consumed, st) {
            return n0("pass");
        }
        return st.clone();
    }
    if op == "func_def" {
        let new_body = Val::List(fe_subst_pass_list(&body_list(&st.get(3)), consumed));
        if st.len() > 6 {
            return Val::node("func_def", vec![st.get(1), st.get(2), new_body,
                                              st.get(4), st.get(5), st.get(6)]);
        }
        return Val::node("func_def", vec![st.get(1), st.get(2), new_body,
                                          st.get(4), st.get(5)]);
    }
    if op == "class_def" {
        return Val::node("class_def", vec![st.get(1), st.get(2),
                                           Val::List(fe_subst_pass_list(&body_list(&st.get(3)), consumed))]);
    }
    if op == "if" {
        return Val::node("if", vec![st.get(1),
                                    Val::List(fe_subst_pass_list(&body_list(&st.get(2)), consumed)),
                                    Val::List(fe_subst_pass_list(&body_list(&st.get(3)), consumed))]);
    }
    if op == "while" {
        return Val::node("while", vec![st.get(1),
                                       Val::List(fe_subst_pass_list(&body_list(&st.get(2)), consumed))]);
    }
    if op == "for" {
        return Val::node("for", vec![st.get(1), st.get(2),
                                     Val::List(fe_subst_pass_list(&body_list(&st.get(3)), consumed)),
                                     st.get(4)]);
    }
    if op == "match" {
        let mut ncases: Vec<Val> = Vec::new();
        for cs in body_list(&st.get(2)) {
            ncases.push(Val::node("match_case", vec![cs.get(1), cs.get(2),
                                                     Val::List(fe_subst_pass_list(&body_list(&cs.get(3)), consumed))]));
        }
        return Val::node("match", vec![st.get(1), Val::List(ncases)]);
    }
    st.clone()
}

fn fe_hoist_nested(modv: Val, seen: &mut Vec<String>, stack: &mut [String],
                   alias_names: &mut Vec<String>, alias_exports: &mut Exports) -> Val {
    let stmts = body_list(&modv.get(1));
    let mut inserts: Vec<Vec<Val>> = Vec::new();
    let mut consumed: Vec<Val> = Vec::new();
    let mut any_consumed = false;
    for st in &stmts {
        let mut found: Vec<Val> = Vec::new();
        fe_collect_imports_into(st, &mut found);
        let mut spliced: Vec<Val> = Vec::new();
        for nd in &found {
            let op = nd.head();
            if op == "from_import" {
                let fmod = nd.get(1);
                let fnlevel = nd.get(3);
                let fmod_str = match &fmod { Val::Str(s) => s.clone(), _ => String::new() };
                if matches!(fmod, Val::Null) || !matches!(fnlevel, Val::Int(0))
                    || fmod_str.contains('.')
                {
                    continue;
                }
                let fpath = format!("{}.si", fmod_str);
                if Path::new(&fpath).exists() {
                    let more = fe_load_splice(&fpath, &fmod_str, seen, stack,
                                              alias_names, alias_exports);
                    for s in more { spliced.push(s); }
                    consumed.push(nd.clone());
                    any_consumed = true;
                }
            } else {
                let pairs = body_list(&nd.get(1));
                let mut all_ok = !pairs.is_empty();
                for pr in &pairs {
                    let nm = pr.get(0).as_str();
                    let path = format!("{}.si", nm);
                    if Path::new(&path).exists() {
                        let more2 = fe_load_splice(&path, &nm, seen, stack,
                                                   alias_names, alias_exports);
                        for s2 in more2 { spliced.push(s2); }
                        let asn2 = pr.get(1);
                        if !matches!(asn2, Val::Null) && asn2.as_str() != nm {
                            fe_register_alias(&asn2.as_str(), &nm, alias_names, alias_exports);
                        }
                    } else {
                        all_ok = false;
                    }
                }
                if all_ok {
                    consumed.push(nd.clone());
                    any_consumed = true;
                }
            }
        }
        inserts.push(spliced);
    }
    let mut out: Vec<Val> = Vec::new();
    for (i, st) in stmts.iter().enumerate() {
        let sp = inserts[i].clone();
        if !sp.is_empty() && !out.is_empty() {
            let last = out.last().unwrap().clone();
            if last.is_node() && last.head() == "line" {
                let marker = out.pop().unwrap();
                for s3 in sp { out.push(s3); }
                out.push(marker);
            } else {
                for s3 in sp { out.push(s3); }
            }
        } else {
            for s3 in sp { out.push(s3); }
        }
        if any_consumed {
            out.push(fe_subst_pass_stmt(st, &consumed));
        } else {
            out.push(st.clone());
        }
    }
    ns2("module", Val::List(out))
}

fn fe_rewrite_aliases(node: &Val, alias_names: &[String], alias_exports: &Exports) -> Val {
    if node.is_scalar() {
        return node.clone();
    }
    if node.is_node() {
        if node.head() == "attribute" && node.len() >= 3 {
            let base = node.get(1);
            if base.is_node() && base.head() == "name" {
                let an = base.get(1).as_str();
                let ai = fe_alias_index(alias_names, &an);
                if ai >= 0 && export_list_contains(&alias_exports[ai as usize],
                                                   &node.get(2).as_str()) {
                    return ns2("name", node.get(2));
                }
            }
        }
        let mut out = vec![Val::s(node.head())];
        for c in body_list(node).into_iter().skip(1) {
            out.push(fe_rewrite_aliases(&c, alias_names, alias_exports));
        }
        return Val::List(out);
    }
    // plain list
    let mut out2: Vec<Val> = Vec::new();
    for c in body_list(node) {
        out2.push(fe_rewrite_aliases(&c, alias_names, alias_exports));
    }
    Val::List(out2)
}

// ---------- nested def / lambda hoisting ----------

struct HG {
    prefix: String,
    ren_src: Vec<String>,
    ren_dst: Vec<String>,
    counter: i64,
    locals: Vec<String>,
}

fn hg_lookup(g: &HG, name: &str) -> String {
    for (i, s) in g.ren_src.iter().enumerate() {
        if s == name {
            return g.ren_dst[i].clone();
        }
    }
    String::new()
}

fn hoist_mentions(node: &Val, name: &str) -> bool {
    if node.is_scalar() { return false; }
    if node.is_node()
        && node.head() == "name" && node.len() == 2 && node.get(1).as_str() == name {
            return true;
        }
    body_list(node).iter().any(|c| hoist_mentions(c, name))
}

fn hoist_calls_one_of(node: &Val, names: &[String]) -> bool {
    if node.is_scalar() { return false; }
    if node.is_node() && node.head() == "call" {
        let callee = node.get(1);
        if callee.is_node() && callee.head() == "name"
            && hg_in_list(names, &callee.get(1).as_str()) {
                return true;
            }
    }
    body_list(node).iter().any(|c| hoist_calls_one_of(c, names))
}

fn hoist_collect_locals(node: &Val, out: &mut Vec<String>) {
    if !matches!(node, Val::List(_)) { return; }
    if node.len() >= 2 && node.is_node() {
        let op = node.head();
        if (op == "assign" || op == "ann_assign" || op == "aug_assign")
            && node.get(1).str_or().is_some()
        {
            out.push(node.get(1).as_str());
        } else if op == "tuple_assign" {
            for target in body_list(&node.get(1)) {
                if let Some(t) = target.str_or() {
                    out.push(t);
                } else if target.is_node() && target.len() >= 2
                    && target.head() == "name" && target.get(1).str_or().is_some()
                {
                    out.push(target.get(1).as_str());
                }
            }
        } else if op == "for" || op == "c_for" {
            let target2 = node.get(1);
            if let Some(t) = target2.str_or() {
                out.push(t);
            } else if target2.is_node() && target2.len() >= 2
                && target2.head() == "name" && target2.get(1).str_or().is_some()
            {
                out.push(target2.get(1).as_str());
            } else if target2.is_node() && target2.len() >= 2
                && target2.head() == "tuple_unpack"
            {
                for name in body_list(&target2.get(1)) {
                    out.push(name.as_str());
                }
            }
        } else if op == "func_def" {
            out.push(node.get(1).as_str());
            return;
        }
    }
    if let Val::List(items) = node {
        for c in items {
            if matches!(c, Val::List(_)) {
                hoist_collect_locals(c, out);
            }
        }
    }
}

fn hoist_collect_assigned(stmts: &Val, sink: &mut Vec<String>) {
    let items = body_list(stmts);
    for st in &items {
        if !st.is_node() || st.len() == 0 {
            continue;
        }
        let op = st.head();
        if op == "assign" || op == "ann_assign" || op == "aug_assign" {
            let tgt = st.get(1);
            if let Some(t) = tgt.str_or() {
                sink.push(t);
            } else if tgt.is_node() && tgt.len() >= 2 && tgt.head() == "name" {
                sink.push(tgt.get(1).as_str());
            }
        } else if op == "for" && st.len() >= 2 {
            let t = st.get(1);
            if let Some(x) = t.str_or() {
                sink.push(x);
            } else if t.is_node() && t.len() >= 2 && t.head() == "name" {
                sink.push(t.get(1).as_str());
            }
            let body = if st.len() > 3 { st.get(3) } else { Val::List(vec![]) };
            hoist_collect_locals(&body, sink);
        } else if op == "if" && st.len() >= 4 {
            hoist_collect_locals(&st.get(2), sink);
            hoist_collect_locals(&st.get(3), sink);
        } else if op == "while" && st.len() >= 3 {
            hoist_collect_locals(&st.get(2), sink);
        }
    }
}

fn hoist_free_names(node: &Val, out: &mut Vec<String>) {
    if node.is_scalar() { return; }
    if node.is_node()
        && node.head() == "name" && node.len() == 2 {
            let nm = node.get(1).as_str();
            if !hg_in_list(out, &nm) {
                out.push(nm);
            }
            return;
        }
    for c in body_list(node) {
        hoist_free_names(&c, out);
    }
}

fn hoist_insert_self(body: &Val, needing: &[String]) -> Val {
    if body.is_scalar() { return body.clone(); }
    if body.is_node() && body.head() == "call" {
        let callee = body.get(1);
        if callee.is_node() && callee.head() == "name"
            && hg_in_list(needing, &callee.get(1).as_str()) {
                let mut new_args = vec![ns2("name", Val::s("self"))];
                for a in body_list(&body.get(2)) {
                    new_args.push(hoist_insert_self(&a, needing));
                }
                return Val::node("call", vec![callee, Val::List(new_args), body.get(3)]);
            }
    }
    if body.is_node() {
        let mut out2 = vec![Val::s(body.head())];
        for c in body_list(body).into_iter().skip(1) {
            out2.push(hoist_insert_self(&c, needing));
        }
        return Val::List(out2);
    }
    let mut out: Vec<Val> = Vec::new();
    for c in body_list(body) {
        out.push(hoist_insert_self(&c, needing));
    }
    Val::List(out)
}

// returns None where the spec returns None (nested func_def consumed)
fn hoist_rec(node: &Val, g: &mut HG, hoisted: &mut Vec<Val>) -> Option<Val> {
    if node.is_scalar() {
        return Some(node.clone());
    }
    let mut op = "";
    if node.is_node() {
        op = node.head();
    }
    if op == "func_def" {
        let mangled = format!("{}__{}", g.prefix, node.get(1).as_str());
        g.ren_src.push(node.get(1).as_str());
        g.ren_dst.push(mangled.clone());
        let bodyv = node.get(3);
        let body_opt = hoist_rec(&bodyv, g, hoisted);
        let body = body_opt.unwrap_or(Val::List(vec![]));
        let exp_flag = if node.len() > 6 { node.get(6) } else { Val::Null };
        if !matches!(exp_flag, Val::Null) {
            hoisted.push(Val::node("func_def", vec![Val::s(&mangled), node.get(2),
                                                    body, node.get(4), node.get(5), exp_flag]));
        } else {
            hoisted.push(Val::node("func_def", vec![Val::s(&mangled), node.get(2),
                                                    body, node.get(4), node.get(5)]));
        }
        return None;
    }
    if op == "lambda" {
        g.counter += 1;
        let mangled2 = format!("{}__L{}", g.prefix, g.counter);
        if hoist_mentions(&node.get(2), "self") {
            eprintln!("M4 hoist error: lambda capturing 'self' is not supported; use a nested def");
            std::process::exit(1);
        }
        let lbody = hoist_rec(&node.get(2), g, hoisted).unwrap_or(Val::Null);
        let params = node.get(1);
        let annos: Vec<Val> = body_list(&params).iter().map(|_| Val::Null).collect();
        hoisted.push(Val::node("func_def", vec![Val::s(&mangled2), params,
                                                Val::List(vec![ns2("return", lbody)]),
                                                Val::List(annos), Val::Null]));
        return Some(ns2("funcref", Val::s(&mangled2)));
    }
    if op == "call" {
        let callee = node.get(1);
        if callee.is_node() && callee.head() == "name" {
            let m2 = hg_lookup(g, &callee.get(1).as_str());
            if !m2.is_empty() {
                let mut new_args2: Vec<Val> = Vec::new();
                for a in body_list(&node.get(2)) {
                    new_args2.push(hoist_rec(&a, g, hoisted).unwrap_or(Val::Null));
                }
                return Some(Val::node("call", vec![ns2("name", Val::s(&m2)),
                                                   Val::List(new_args2), node.get(3)]));
            }
        }
    }
    if op == "name" {
        let nm3 = node.get(1).as_str();
        let m4 = hg_lookup(g, &nm3);
        if !m4.is_empty() && !hg_in_list(&g.locals, &nm3) {
            return Some(ns2("funcref", Val::s(&m4)));
        }
    }
    if node.is_node() {
        let mut out3 = vec![Val::s(op)];
        for c in body_list(node).into_iter().skip(1) {
            out3.push(hoist_rec(&c, g, hoisted).unwrap_or(Val::Null));
        }
        return Some(Val::List(out3));
    }
    let mut out4: Vec<Val> = Vec::new();
    for c in body_list(node) {
        if let Some(r2) = hoist_rec(&c, g, hoisted) {
            out4.push(r2);
        }
    }
    Some(Val::List(out4))
}

fn hoist_def(func_def: &Val, cls_name: &str, is_method: bool,
             global_names: &[String], extra: &mut Vec<Val>) -> Val {
    let mut prefix = func_def.get(1).as_str();
    if !cls_name.is_empty() {
        prefix = format!("{}__{}", cls_name, func_def.get(1).as_str());
    }
    let mut g_locals: Vec<String> = Vec::new();
    hoist_collect_assigned(&func_def.get(3), &mut g_locals);
    let mut g = HG {
        prefix: prefix.clone(),
        ren_src: Vec::new(),
        ren_dst: Vec::new(),
        counter: 0,
        locals: g_locals,
    };
    let mut hoisted: Vec<Val> = Vec::new();
    let new_body = hoist_rec(&func_def.get(3), &mut g, &mut hoisted)
        .unwrap_or(Val::List(vec![]));

    let mut needing: Vec<String> = Vec::new();
    for h in &hoisted {
        if hoist_mentions(&h.get(3), "self") {
            needing.push(h.get(1).as_str());
        }
    }
    let mut changed = true;
    while changed {
        changed = false;
        for h2 in &hoisted {
            let mangled = h2.get(1).as_str();
            if !hg_in_list(&needing, &mangled)
                && hoist_calls_one_of(&h2.get(3), &needing) {
                    needing.push(mangled);
                    changed = true;
                }
        }
    }

    let mut final_defs: Vec<Val> = Vec::new();
    for h3 in &hoisted {
        let mut h3v = h3.clone();
        let mangled2 = h3.get(1).as_str();
        let mut body2 = h3.get(3);
        let params = h3.get(2);
        let annos2 = h3.get(4);
        if hg_in_list(&needing, &mangled2) {
            body2 = hoist_insert_self(&body2, &needing);
            let cls_anno = if !cls_name.is_empty() {
                ns2("name", Val::s(cls_name))
            } else {
                Val::Null
            };
            let mut new_params = vec![Val::s("self")];
            for pv in body_list(&params) {
                new_params.push(pv);
            }
            let mut new_annos = vec![cls_anno];
            for av in body_list(&annos2) {
                new_annos.push(av);
            }
            h3v = Val::node("func_def", vec![Val::s(&mangled2), Val::List(new_params),
                                             body2, Val::List(new_annos), h3.get(5)]);
        }
        let mut free: Vec<String> = Vec::new();
        hoist_free_names(&h3v.get(3), &mut free);
        let mut allowed: Vec<String> = global_names.to_vec();
        for nn in &needing {
            allowed.push(nn.clone());
        }
        for pv2 in body_list(&h3v.get(2)) {
            allowed.push(pv2.as_str());
        }
        allowed.push("self".to_string());
        let mut own_locals: Vec<String> = Vec::new();
        hoist_collect_locals(&h3v.get(3), &mut own_locals);
        for ln in &own_locals {
            allowed.push(ln.clone());
        }
        for hn in &hoisted {
            allowed.push(hn.get(1).as_str());
        }
        for fname in &free {
            if !hg_in_list(&allowed, fname) {
                eprintln!("M4 hoist error: nested function '{}' captures '{}'; pass it as a parameter",
                          mangled2, fname);
                std::process::exit(1);
            }
        }
        final_defs.push(h3v);
    }

    let mut new_body = new_body;
    if is_method && !needing.is_empty() {
        new_body = hoist_insert_self(&new_body, &needing);
    }
    for f2 in final_defs {
        extra.push(f2);
    }
    if func_def.len() > 6 {
        return Val::node("func_def", vec![func_def.get(1), func_def.get(2), new_body,
                                          func_def.get(4), func_def.get(5), func_def.get(6)]);
    }
    Val::node("func_def", vec![func_def.get(1), func_def.get(2), new_body,
                               func_def.get(4), func_def.get(5)])
}

const BUILTIN_GLOBALS: &[&str] = &[
    "len", "range", "str", "int", "float", "bool", "print", "fmt", "min",
    "max", "abs", "input", "enumerate", "isinstance", "read_stdin",
    "read_file", "ord", "chr", "repr", "tuple", "list", "dict", "set",
    "type", "sorted", "zip", "map", "sum", "any", "all",
];

fn hoist_module(modv: &Val) -> Val {
    let stmts = body_list(&modv.get(1));
    let mut global_names: Vec<String> = BUILTIN_GLOBALS.iter()
        .map(|s| s.to_string()).collect();

    for st in &stmts {
        if st.is_node() {
            let h = st.head();
            if h == "func_def" || h == "class_def"
                || h == "assign" || h == "ann_assign" {
                global_names.push(st.get(1).as_str());
            }
        }
    }

    let mut out: Vec<Val> = Vec::new();
    for st in &stmts {
        if st.is_node() && st.head() == "func_def" {
            let mut extra: Vec<Val> = Vec::new();
            out.push(hoist_def(st, "", false, &global_names, &mut extra));
            for e in extra {
                out.push(e);
            }
        } else if st.is_node() && st.head() == "class_def" {
            let cls_name = st.get(1).as_str();
            let mut new_members: Vec<Val> = Vec::new();
            let mut extra2: Vec<Val> = Vec::new();
            for mm in body_list(&st.get(3)) {
                if mm.is_node() && mm.head() == "func_def" {
                    let mparams = body_list(&mm.get(2));
                    let is_m = !mparams.is_empty() && mparams[0].as_str() == "self";
                    new_members.push(hoist_def(&mm, &cls_name, is_m, &global_names, &mut extra2));
                } else {
                    new_members.push(mm);
                }
            }
            out.push(Val::node("class_def", vec![st.get(1), st.get(2),
                                                 Val::List(new_members)]));
            for e2 in extra2 {
                out.push(e2);
            }
        } else {
            out.push(st.clone());
        }
    }
    ns2("module", Val::List(out))
}

// ---------- JSON emission ----------

fn json_quote(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\t' => out.push_str("\\t"),
            '\r' => out.push_str("\\r"),
            c if (c as u32) < 0x20 => {
                let digits = "0123456789abcdef";
                let c4 = c as u32;
                out.push_str("\\u");
                out.push(digits.chars().nth((c4 / 4096) as usize).unwrap());
                out.push(digits.chars().nth(((c4 / 256) % 16) as usize).unwrap());
                out.push(digits.chars().nth(((c4 / 16) % 16) as usize).unwrap());
                out.push(digits.chars().nth((c4 % 16) as usize).unwrap());
            }
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

fn json_emit(node: &Val, out: &mut String) {
    match node {
        Val::Null => out.push_str("null"),
        Val::Bool(true) => out.push_str("true"),
        Val::Bool(false) => out.push_str("false"),
        Val::Int(i) => out.push_str(&i.to_string()),
        // Rust {:?} always round-trips and keeps the float type
        // distinguishable (1.0, not 1) - python json re-parses both to
        // the same f64, the harness compares canonical values
        Val::Float(f) => out.push_str(&format!("{:?}", f)),
        Val::Str(s) => out.push_str(&json_quote(s)),
        Val::List(items) => {
            out.push('[');
            for (i, child) in items.iter().enumerate() {
                if i > 0 { out.push(','); }
                json_emit(child, out);
            }
            out.push(']');
        }
    }
}

fn json_dumps(node: &Val) -> String {
    let mut out = String::new();
    json_emit(node, &mut out);
    out
}
