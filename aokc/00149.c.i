# 1 "aokc/00149.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00149.c.v2.c" 2
struct S { int a; int b; };
struct S *s = &(struct S) { 1, 2 };

int
main()
{
	if(s->a != 1)
		return 1;
	if(s->b != 2)
		return 2;
	return 0;
}

