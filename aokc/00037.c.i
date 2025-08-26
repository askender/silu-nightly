# 1 "aokc/00037.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00037.c.v2.c" 2
int
main()
{
	int x[2];
	int *p;
	
	x[1] = 7;
	p = &x[0];
	p = p + 1;
	
	if(*p != 7)
		return 1;
	if(&x[1] - &x[0] != 1)
		return 1;
	
	return 0;
}

