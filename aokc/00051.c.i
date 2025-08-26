# 1 "aokc/00051.c.v2.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 464 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "aokc/00051.c.v2.c" 2
int x = 0;

int
main()
{
	switch(x)
		case 0:
			;
	switch(x)
		case 0:
			switch(x) {
				case 0:
					goto next;
				default:
					return 1;
			}
	return 1;
	next:
	switch(x)
		case 1:
			return 1;
	switch(x) {
		{
			x = 1 + 1;
			foo:
			case 1:
				return 1;
		}
	}
	switch(x) {
		case 0:
			return x;
		case 1:
			return 1;
		default:
			return 1;
	}
}

