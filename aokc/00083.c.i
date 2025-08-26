# 1 "aokc/00083.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00083.c.v2.c" 2


int
one(int a)
{
	if (a != 1)
		return 1;
	
	return 0;
}

int
two(int a, int b)
{
	if (a != 1)
		return 1;
	if (b != 2)
		return 1;
	
	return 0;
}

int
three(int a, int b, int c)
{
	if (a != 1)
		return 1;
	if (b != 2)
		return 1;
	if (c != 3)
		return 1;
	
	return 0;
}

int
main()
{
	if (one( 1))
		return 2;
	if (two( 1, 2))
		return 3;
	if (three( 1, 2, 3))
		return 4;
	
	return 0;
}

