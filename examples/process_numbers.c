
int process_numbers(int a, int b) {
  int sum = 0;

  if (b == 0) {
    return -1;
  } else if (b > 10) {
    sum = a + b;
  } else {
    sum = a - b;
  }

  for (int i = 0; i < b; i++) {
    sum += i;
    if (sum > 100) {
      return 999;
    }
  }

  return sum / b;
}
