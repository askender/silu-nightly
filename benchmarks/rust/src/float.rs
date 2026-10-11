fn main() {
    let mut acc: f64 = 0.0;
    let mut i: i64 = 0;
    while i < 200000 {
        acc = acc + 1.5 * 2.25 + (i as f64) / 4.0;
        i += 1;
    }
    println!("{:?}", acc);
}
