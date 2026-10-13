// Mirror of ../jsonparse.si: recursive descent JSON (objects, arrays,
// strings, ints) over a deterministically generated document.
use std::collections::HashMap;

enum Json {
    Int(i64),
    Str(String),
    Arr(Vec<Json>),
    Obj(HashMap<String, Json>),
}

fn parse_string(b: &[u8], pos: &mut usize) -> String {
    *pos += 1;
    let start = *pos;
    while b[*pos] != b'"' {
        *pos += 1;
    }
    let out = String::from_utf8(b[start..*pos].to_vec()).unwrap();
    *pos += 1;
    out
}

fn parse_number(b: &[u8], pos: &mut usize) -> i64 {
    let mut n: i64 = 0;
    while *pos < b.len() && b[*pos].is_ascii_digit() {
        n = n * 10 + (b[*pos] - b'0') as i64;
        *pos += 1;
    }
    n
}

fn parse_value(b: &[u8], pos: &mut usize) -> Json {
    match b[*pos] {
        b'{' => {
            *pos += 1;
            let mut obj = HashMap::new();
            while b[*pos] != b'}' {
                let key = parse_string(b, pos);
                *pos += 1; // colon
                obj.insert(key, parse_value(b, pos));
                if b[*pos] == b',' {
                    *pos += 1;
                }
            }
            *pos += 1;
            Json::Obj(obj)
        }
        b'[' => {
            *pos += 1;
            let mut arr = Vec::new();
            while b[*pos] != b']' {
                arr.push(parse_value(b, pos));
                if b[*pos] == b',' {
                    *pos += 1;
                }
            }
            *pos += 1;
            Json::Arr(arr)
        }
        b'"' => Json::Str(parse_string(b, pos)),
        _ => Json::Int(parse_number(b, pos)),
    }
}

fn main() {
    let mut doc = String::from("[");
    let mut i = 0;
    while i < 3000 {
        doc.push_str(&format!("{{\"id\":{},\"name\":\"item{}\"}}", i, i));
        if i + 1 < 3000 {
            doc.push(',');
        }
        i += 1;
    }
    doc.push(']');

    let mut pos = 0usize;
    let data = parse_value(doc.as_bytes(), &mut pos);
    if let Json::Arr(items) = data {
        let mut total: i64 = 0;
        for item in &items {
            if let Json::Obj(map) = item {
                if let Json::Int(v) = map["id"] {
                    total += v;
                }
            }
        }
        println!("{} {}", total, items.len());
    }
}
