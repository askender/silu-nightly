int simple_add(int x, int y) {
  int result = x + y;
  return result;
}

int test_if(int a) {
  if (a > 0) {
    return 1;
  } else {
    return -1;
  }
}

int test_for_loop(int n) {
  int sum = 0;
  int i;
  for (i = 0; i < n; i++) {
    sum = sum + i;
  }
  return sum;
}

int test_while_loop(int count) {
  int result = 1;
  while (count > 0) {
    result = result * 2;
    count = count - 1;
  }
  return result;
}

int main() {
  int a = 5;
  int b = 3;
  int sum = simple_add(a, b);

  int sign = test_if(a);
  int loop_sum = test_for_loop(3);
  int power = test_while_loop(4);

  return sum + sign + loop_sum + power;
}
