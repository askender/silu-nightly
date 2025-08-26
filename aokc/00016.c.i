# 1 "aokc/00016.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00016.c.v2.c" 2
int
main()
{
	int arr[2];
	int *p;
	
	p = &arr[1];
	*p = 0;
	return arr[1];
}

