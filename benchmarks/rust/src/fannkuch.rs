// Fannkuch (odometer permutations + pancake flips), n=10.
// Matches benchmarks/fannkuch.si exactly.

fn main() {
    let n: i64 = 10;
    let mut perm: Vec<i64> = vec![0; n as usize];
    let mut perm1: Vec<i64> = vec![0; n as usize];
    let mut max_flips: i64 = 0;
    let mut checksum: i64 = 0;

    let mut i: i64 = 0;
    while i < n {
        perm1[i as usize] = i;
        i += 1;
    }

    let mut r: i64 = n;
    while r > 0 {
        let mut i: i64 = 0;
        while i < n {
            perm[i as usize] = perm1[i as usize];
            i += 1;
        }
        let mut flips: i64 = 0;
        let mut k = perm1[0];
        while k != 0 {
            let mut i: i64 = 0;
            let mut j: i64 = k;
            while i < j {
                let tmp = perm[i as usize];
                perm[i as usize] = perm[j as usize];
                perm[j as usize] = tmp;
                i += 1;
                j -= 1;
            }
            flips += 1;
            k = perm[0];
        }
        if flips > max_flips {
            max_flips = flips;
        }
        checksum += flips;

        let mut i: i64 = 0;
        while r > 0 {
            if i == n {
                r = 0;
                break;
            }
            let j = perm1[0];
            let mut k: i64 = 1;
            while k <= i {
                perm1[(k - 1) as usize] = perm1[k as usize];
                k += 1;
            }
            perm1[i as usize] = j;
            i += 1;
            if i >= r {
                break;
            }
        }
        r -= 1;
    }
    println!("{} {}", checksum, max_flips);
}
