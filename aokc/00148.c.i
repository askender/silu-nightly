# 1 "aokc/00148.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00148.c.v2.c" 2
struct S {int a; int b;};
struct S arr[2] = {[1] = {3, 4}, [0] = {1, 2}};

int
main()
{
	if(arr[0].a != 1)
		return 1;
	if(arr[0].b != 2)
		return 2;
	if(arr[1].a != 3)
		return 3;
	if(arr[1].b != 4)
		return 4;
	return 0;
}

