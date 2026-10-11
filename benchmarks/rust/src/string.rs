fn main() {
    // s = s + "x" mirrors the Python benchmark exactly: a fresh string
    // allocation per step (quadratic), not an amortized push_str.
    let mut s: String = String::new();
    let mut i: i64 = 0;
    while i < 3000 {
        s = s + "x";
        i += 1;
    }
    println!("{}", s.len());
}
