# 1 "aokc/00135.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00135.c.v2.c" 2
int
main(void)
{
	long long i;
	unsigned long long u;

	i = 1;
	i = -1;
	i = -1l;
	i = -1u;
	i = -1ll;
	i = -1ll & 3;
	i = -1ll < 0;

	u = 1;
	u = -1;
	u = -1l;
	u = -1u;
	u = -1ll;
	u = -1llu & 3;
	u = -1llu < 0;
	return 0;
}

