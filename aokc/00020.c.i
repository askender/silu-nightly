# 1 "aokc/00020.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00020.c.v2.c" 2
int
main()
{
	int x, *p, **pp;
	
	x = 0;
	p = &x;
	pp = &p;
	return **pp;
}

