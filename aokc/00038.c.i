# 1 "aokc/00038.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00038.c.v2.c" 2
int
main()
{
	int x, *p;

	if (sizeof(0) < 2)
		return 1;
	if (sizeof 0 < 2)
		return 1;
	if (sizeof(char) < 1)
		return 1;
	if (sizeof(int) - 2 < 0)
		return 1;
	if (sizeof(&x) != sizeof p)
		return 1;
	return 0;
}

