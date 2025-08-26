# 1 "aokc/00095.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00095.c.v2.c" 2
int x;
int x = 3;
int x;

int main();

void *
foo()
{
	return &main;
}

int
main()
{
	if (x != 3)
		return 0;

	x = 0;
	return x;
}


