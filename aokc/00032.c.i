# 1 "aokc/00032.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00032.c.v2.c" 2
int
main()
{
	int arr[2];
	int *p;
	
	arr[0] = 2;
	arr[1] = 3;
	p = &arr[0];
	if(*(p++) != 2)
		return 1;
	if(*(p++) != 3)
		return 2;
	
	p = &arr[1];
	if(*(p--) != 3)
		return 1;
	if(*(p--) != 2)
		return 2;
		
	p = &arr[0];
	if(*(++p) != 3)
		return 1;
	
	p = &arr[1];
	if(*(--p) != 2)
		return 1;

	return 0;
}

