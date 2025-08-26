#include <stdio.h>

static int fred = 1234;

void henry()
{
   static int fred = 4567;

   printf("%d\n", fred);
   fred++;
}

int main()
{
   printf("%d\n", fred);
   henry();
   henry();
   henry();
   henry();
   printf("%d\n", fred);
   return 0;
}
