# 1 "aokc/00005.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00005.c.v2.c" 2
int
main()
{
	int x;
	int *p;
	int **pp;

	x = 0;
	p = &x;
	pp = &p;

	if(*p)
		return 1;
	if(**pp)
		return 1;
	else
		**pp = 1;

	if(x)
		return 0;
	else
		return 1;
}

