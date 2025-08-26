# 1 "aokc/00104.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00104.c.v2.c" 2
# 1 "mystdint/stdint.h" 1



typedef signed int       int32_t;
typedef long long int    int64_t;


# 2 "aokc/00104.c.v2.c" 2

int
main()
{
	int32_t x;
	int64_t l;
	
	x = 0;
	l = 0;
	
	x = ~x;
	if (x != 0xffffffff)
		return 1;
	
	l = ~l;
	if (x != 0xffffffffffffffff)
		return 2;

	
	return 0;
}

