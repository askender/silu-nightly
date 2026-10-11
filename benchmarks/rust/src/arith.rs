fn main() {
    let mut total: i64 = 0;
    let mut i: i64 = 0;
    while i < 300000 {
        total += i % 7;
        total -= i / 3;
        i += 1;
    }
    println!("{}", total);
}
