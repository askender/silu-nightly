// Mandelbrot ASCII, matches benchmarks/mandelbrot.si (80x24, 50 iters).

fn main() {
    let width: i64 = 80;
    let height: i64 = 24;
    let max_iter: i64 = 50;

    let mut y: i64 = 0;
    while y < height {
        let mut row = String::new();
        let mut x: i64 = 0;
        while x < width {
            let c_re = (x as f64) * 3.5 / (width as f64) - 2.5;
            let c_im = (y as f64) * 2.0 / (height as f64) - 1.0;
            let mut z_re = 0.0f64;
            let mut z_im = 0.0f64;
            let mut iter: i64 = 0;
            while iter < max_iter {
                let zr2 = z_re * z_re;
                let zi2 = z_im * z_im;
                if zr2 + zi2 > 4.0 {
                    break;
                }
                z_im = 2.0 * z_re * z_im + c_im;
                z_re = zr2 - zi2 + c_re;
                iter += 1;
            }
            if iter == max_iter {
                row = row + "*";
            } else {
                row = row + " ";
            }
            x += 1;
        }
        println!("{}", row);
        y += 1;
    }
}
