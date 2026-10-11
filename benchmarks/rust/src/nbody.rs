// N-body simulation, SoA layout matching benchmarks/nbody.si.

const SOLAR_MASS: f64 = 4.0 * std::f64::consts::PI * std::f64::consts::PI;
const DAYS_PER_YEAR: f64 = 365.24;

struct System {
    xs: Vec<f64>,
    ys: Vec<f64>,
    zs: Vec<f64>,
    vx: Vec<f64>,
    vy: Vec<f64>,
    vz: Vec<f64>,
    mass: Vec<f64>,
}

impl System {
    fn new() -> System {
        let mut s = System {
            xs: vec![0.0],
            ys: vec![0.0],
            zs: vec![0.0],
            vx: vec![0.0],
            vy: vec![0.0],
            vz: vec![0.0],
            mass: vec![SOLAR_MASS],
        };
        let bodies: Vec<[f64; 7]> = vec![
            // jupiter
            [
                4.84143144246472090,
                -1.16032004402742839,
                -0.19964705344137988,
                1.66007664274403694e-03 * DAYS_PER_YEAR,
                7.69901118419740425e-03 * DAYS_PER_YEAR,
                -6.90460016972063023e-04 * DAYS_PER_YEAR,
                9.54791938424326609e-04,
            ],
            // saturn
            [
                8.34336671824457987,
                4.12479856412430479,
                -4.03523417114321381e-01,
                -2.76742510726862411e-03 * DAYS_PER_YEAR,
                4.99852801234917238e-03 * DAYS_PER_YEAR,
                2.30417297573763929e-05 * DAYS_PER_YEAR,
                2.85885980666130812e-04,
            ],
            // uranus
            [
                1.28943695621391310e+01,
                -1.51111514016986312e+01,
                -2.23307578892655734e-01,
                2.96460137564761618e-03 * DAYS_PER_YEAR,
                2.37847173959480950e-03 * DAYS_PER_YEAR,
                -2.96589568540237556e-05 * DAYS_PER_YEAR,
                4.36624404335156298e-05,
            ],
            // neptune
            [
                1.53796971148509165e+01,
                -2.59193146099879641e+01,
                1.79258772950371181e-01,
                2.68067772490389322e-03 * DAYS_PER_YEAR,
                -1.62813114750985960e-03 * DAYS_PER_YEAR,
                -9.51592254519715870e-05 * DAYS_PER_YEAR,
                5.15138902046611451e-05,
            ],
        ];
        for b in bodies {
            s.xs.push(b[0]);
            s.ys.push(b[1]);
            s.zs.push(b[2]);
            s.vx.push(b[3]);
            s.vy.push(b[4]);
            s.vz.push(b[5]);
            s.mass.push(b[6]);
        }
        // momentum correction
        let mut px = 0.0;
        let mut py = 0.0;
        let mut pz = 0.0;
        for i in 1..s.mass.len() {
            px += s.vx[i] * s.mass[i];
            py += s.vy[i] * s.mass[i];
            pz += s.vz[i] * s.mass[i];
        }
        s.vx[0] = -px / SOLAR_MASS;
        s.vy[0] = -py / SOLAR_MASS;
        s.vz[0] = -pz / SOLAR_MASS;
        s
    }

    fn energy(&self) -> f64 {
        let n = self.mass.len();
        let mut e = 0.0;
        for i in 0..n {
            let (x1, y1, z1) = (self.xs[i], self.ys[i], self.zs[i]);
            let (vx1, vy1, vz1) = (self.vx[i], self.vy[i], self.vz[i]);
            e += 0.5 * self.mass[i] * (vx1 * vx1 + vy1 * vy1 + vz1 * vz1);
            for j in (i + 1)..n {
                let dx = x1 - self.xs[j];
                let dy = y1 - self.ys[j];
                let dz = z1 - self.zs[j];
                let dist = (dx * dx + dy * dy + dz * dz).sqrt();
                e += (self.mass[i] * self.mass[j]) / dist;
            }
        }
        e
    }

    fn advance(&mut self, dt: f64) {
        let n = self.mass.len();
        for i in 0..n {
            let (x1, y1, z1) = (self.xs[i], self.ys[i], self.zs[i]);
            for j in (i + 1)..n {
                let dx = x1 - self.xs[j];
                let dy = y1 - self.ys[j];
                let dz = z1 - self.zs[j];
                let dist2 = dx * dx + dy * dy + dz * dz;
                let dist = dist2.sqrt();
                let mag = dt / (dist2 * dist);
                // matches nbody.si: magnitude scaled by mass[j] via m_agg
                self.vx[j] += dx * mag * self.mass[j];
                self.vy[j] += dy * mag * self.mass[j];
                self.vz[j] += dz * mag * self.mass[j];
            }
        }
        for i in 0..n {
            self.xs[i] += dt * self.vx[i];
            self.ys[i] += dt * self.vy[i];
            self.zs[i] += dt * self.vz[i];
        }
    }
}

fn main() {
    let mut sys = System::new();
    println!("{:.9}", sys.energy());
    for _ in 0..50000 {
        sys.advance(0.01);
    }
    println!("{:.9}", sys.energy());
}
