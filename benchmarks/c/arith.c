/* Twin of benchmarks/arith.si: while + mod/floordiv + aug assign. */
#include <stdio.h>
int main(void) {
    long total = 0;
    for (long i = 0; i < 300000; i++) {
        total += i % 7;
        total -= i / 3;
    }
    printf("%ld\n", total);
    return 0;
}
