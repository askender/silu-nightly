# 1 "aokc/00093.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00093.c.v2.c" 2
int a[] = {1, 2, 3, 4};

int
main()
{
	if (sizeof(a) != 4*sizeof(int))
		return 1;
	
	return 0;
}

