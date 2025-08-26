# 1 "aokc/00089.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00089.c.v2.c" 2
int
zero()
{
	return 0;
}

struct S
{
	int (*zerofunc)();
} s = { &zero };

struct S *
anon()
{
	return &s;
}

typedef struct S * (*fty)();

fty
go()
{
	return &anon;
}

int
main()
{
	return go()()->zerofunc();
}

