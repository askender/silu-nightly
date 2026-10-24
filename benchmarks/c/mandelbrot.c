#include <stdio.h>
#include <string.h>
/* Mandelbrot twin of benchmarks/mandelbrot.si: 80x24, 50 iters, ASCII */
int main(void) {
    int width = 80, height = 24, max_iter = 50;
    for (int y = 0; y < height; y++) {
        char row[81];
        int p = 0;
        for (int x = 0; x < width; x++) {
            double c_re = (x * 3.5) / width - 2.5;
            double c_im = (y * 2.0) / height - 1.0;
            double z_re = 0.0, z_im = 0.0;
            int iter = 0;
            while (iter < max_iter) {
                double zr2 = z_re * z_re;
                double zi2 = z_im * z_im;
                if (zr2 + zi2 > 4.0) break;
                z_im = 2.0 * z_re * z_im + c_im;
                z_re = zr2 - zi2 + c_re;
                iter++;
            }
            row[p++] = iter == max_iter ? '*' : ' ';
        }
        row[p] = 0;
        printf("%s\n", row);
    }
    return 0;
}
