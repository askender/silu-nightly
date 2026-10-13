// Mirror of ../knucleotide.si
use std::collections::HashMap;

fn main() {
    let n: i64 = 200000;
    let mut dna = String::new();
    let mut state: i64 = 42;
    let mut i: i64 = 0;
    while i < n {
        state = (state * 48271 + 11) % 2147483647;
        let r = state % 4;
        dna.push(match r {
            0 => 'A',
            1 => 'C',
            2 => 'G',
            _ => 'T',
        });
        i += 1;
    }

    let k: usize = 4;
    let bytes = dna.as_bytes();
    let mut counts: HashMap<String, i64> = HashMap::new();
    let mut i: usize = 0;
    while i + k <= bytes.len() {
        let mer = std::str::from_utf8(&bytes[i..i + k]).unwrap();
        *counts.entry(mer.to_string()).or_insert(0) += 1;
        i += 1;
    }

    let mut total: i64 = 0;
    let mut i: usize = 0;
    while i + k <= bytes.len() {
        let mer = std::str::from_utf8(&bytes[i..i + k]).unwrap();
        total += counts.get(mer).copied().unwrap_or(0);
        i += 1;
    }
    println!(
        "{} {} {} {}",
        total,
        counts.len(),
        counts.get("AAAA").copied().unwrap_or(0),
        counts.get("ACGT").copied().unwrap_or(0)
    );
}
