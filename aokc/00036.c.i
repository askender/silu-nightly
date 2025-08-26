# 1 "aokc/00036.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00036.c.v2.c" 2
int
main()
{
	int x;
	
	x = 0;
	x += 2;
	x += 2;
	if (x != 4)
		return 1;
	x -= 1;
	if (x != 3)
		return 2;
	x *= 2;
	if (x != 6)
		return 3;
		
	return 0;
}

