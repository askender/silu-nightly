// 给 int 类型取别名 MyInt
typedef int MyInt;

int test1() {
  MyInt a = 10; // 等价于 int a = 10;
  return 0;
}

typedef int *IntPtr;

int main() {
  IntPtr p1, p2; // 等价于 int *p1, *p2;
  return 0;
}
