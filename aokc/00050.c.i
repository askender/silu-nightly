# 1 "aokc/00050.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00050.c.v2.c" 2
struct S1 {
	int a;
	int b;
};

struct S2 {
	int a;
	int b;
	union {
		int c;
		int d;
	};
	struct S1 s;
};

struct S2 v = {1, 2, 3, {4, 5}};

int
main()
{
	if(v.a != 1)
		return 1;
	if(v.b != 2)
		return 2;
	if(v.c != 3 || v.d != 3)
		return 3;
	if(v.s.a != 4)
		return 4;
	if(v.s.b != 5)
		return 5;
	
	return 0;
}

