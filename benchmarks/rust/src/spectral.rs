// Spectral norm, n=300, matches benchmarks/spectral.si.

fn a(i: i64, j: i64) -> f64 {
    let ij = (i + j) as f64;
    1.0 / ((i + j) * (i + j + 1) / 2 + i + 1) as f64
}

fn multiply(v: &[f64], out: &mut [f64], n: i64) {
    let mut i: i64 = 0;
    while i < n {
        let mut s = 0.0f64;
        let mut j: i64 = 0;
        while j < n {
            s += a(i, j) * v[j as usize];
            j += 1;
        }
        out[i as usize] = s;
        i += 1;
    }
}

fn multiply_transposed(v: &[f64], out: &mut [f64], n: i64) {
    let mut i: i64 = 0;
    while i < n {
        let mut s = 0.0f64;
        let mut j: i64 = 0;
        while j < n {
            s += a(j, i) * v[j as usize];
            j += 1;
        }
        out[i as usize] = s;
        i += 1;
    }
}

fn main() {
    let n: i64 = 300;
    let mut u: Vec<f64> = vec![1.0; n as usize];
    let mut v: Vec<f64> = vec![1.0; n as usize];
    let mut tmp: Vec<f64> = vec![1.0; n as usize];

    let mut iter: i64 = 0;
    while iter < 10 {
        multiply(&u, &mut v, n);
        multiply_transposed(&v, &mut u, n);
        iter += 1;
    }

    let mut v_bv = 0.0f64;
    let mut v_vv = 0.0f64;
    for i in 0..(n as usize) {
        v_bv += u[i] * v[i];
        v_vv += v[i] * v[i];
    }
    println!("{}", (v_bv / v_vv).sqrt());
}
