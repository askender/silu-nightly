# 1 "aokc/00043.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00043.c.v2.c" 2
struct s {
    int x;
    struct {
        int y;
        int z;
    } nest;
};

int
main() {
    struct s v;
    v.x = 1;
    v.nest.y = 2;
    v.nest.z = 3;
    if (v.x + v.nest.y + v.nest.z != 6)
        return 1;
    return 0;
}


