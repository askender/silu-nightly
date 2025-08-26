# 1 "aokc/00103.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00103.c.v2.c" 2
int
main()
{
	int x;
	void *foo;
	void **bar;
	
	x = 0;
	
	foo = (void*)&x;
	bar = &foo;
	
	return **(int**)bar;
}

