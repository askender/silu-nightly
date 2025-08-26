# 1 "aokc/00073.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00073.c.v2.c" 2
int
main()
{
	int arr[2];
	int *p;
	
	p = &arr[1];
	p -= 1;
	*p = 123;
	
	if(arr[0] != 123)
		return 1;
	return 0;
}

