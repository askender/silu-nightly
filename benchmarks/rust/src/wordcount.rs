// Mirror of ../wordcount.si
use std::collections::HashMap;

fn main() {
    let vocab: Vec<String> = (0..100).map(|i| format!("w{}", i)).collect();
    let mut counts: HashMap<String, i64> = HashMap::new();
    let mut i: i64 = 0;
    while i < 300000 {
        let w = &vocab[((i * 48271 + 11) % 100) as usize];
        *counts.entry(w.clone()).or_insert(0) += 1;
        i += 1;
    }

    let mut total: i64 = 0;
    let mut i = 0;
    while i < 100 {
        total += counts[&format!("w{}", i)];
        i += 1;
    }
    println!("{} {}", total, counts.len());
}
