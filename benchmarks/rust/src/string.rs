fn main() {
    // s = s + "x": String: Add<&str> consumes self and reuses the
    // buffer (push_str + move), so this amortizes to O(n) - same as
    // CPython's refcount==1 in-place concat for `s = s + t`.
    let mut s: String = String::new();
    let mut i: i64 = 0;
    while i < 48000 {
        s = s + "x";
        i += 1;
    }
    println!("{}", s.len());
}
