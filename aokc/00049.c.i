# 1 "aokc/00049.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00049.c.v2.c" 2
int x = 10;

struct S {int a; int *p;};
struct S s = { .p = &x, .a = 1};

int
main()
{
	if(s.a != 1)
		return 1;
	if(*s.p != 10)
		return 2;
	return 0;
}

