# 1 "aokc/00106.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00106.c.v2.c" 2
struct S1 { int x; };
struct S2 { struct S1 s1; };

int
main()
{
	struct S2 s2;
	s2.s1.x = 1;
	return 0;
}

