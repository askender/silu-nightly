# 1 "aokc/00024.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00024.c.v2.c" 2
typedef struct { int x; int y; } s;

s v;

int
main()
{
	v.x = 1;
	v.y = 2;
	return 3 - v.x - v.y;
}


