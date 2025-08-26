# 1 "aokc/00017.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00017.c.v2.c" 2
int
main()
{
	struct { int x; int y; } s;
	
	s.x = 3;
	s.y = 5;
	return s.y - s.x - 2; 
}

