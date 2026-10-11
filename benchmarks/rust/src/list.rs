fn main() {
    let mut l: Vec<i64> = Vec::new();
    let mut i: i64 = 0;
    while i < 30000 {
        l.push(i % 100);
        i += 1;
    }

    let mut total: i64 = 0;
    for &x in &l {
        total += x;
    }
    println!("{} {}", total, l.len());
}
