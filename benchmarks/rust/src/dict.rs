use std::collections::HashMap;

fn main() {
    let mut d: HashMap<i64, i64> = HashMap::new();
    let mut i: i64 = 0;
    while i < 20000 {
        d.insert(i % 500, i);
        i += 1;
    }

    let mut total: i64 = 0;
    let mut i: i64 = 0;
    while i < 500 {
        total += d[&i];
        i += 1;
    }
    println!("{} {}", total, d.len());
}
