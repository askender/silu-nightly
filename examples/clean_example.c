int add(int a, int b) {
  int result = a + b;
  return result;
}

int max(int a, int b) {
  if (a > b) {
    return a;
  } else {
    return b;
  }
}

int factorial(int n) {
  int result = 1;
  int i;

  for (i = 1; i <= n; i++) {
    result = result * i;
  }

  return result;
}

int fibonacci(int n) {
  int a = 0;
  int b = 1;
  int temp;
  int count = 0;

  if (n <= 0)
    return 0;
  if (n == 1)
    return 1;

  while (count < n - 1) {
    temp = a + b;
    a = b;
    b = temp;
    count++;
  }

  return b;
}

int sum_array(int arr[], int size) {
  int sum = 0;
  int i;

  for (i = 0; i < size; i++) {
    sum += arr[i];
  }

  return sum;
}

int main() {
  int x = 10;
  int y = 20;
  int z;

  z = add(x, y);

  int maximum = max(x, y);

  int fact = factorial(5);

  if (fact > 100) {
    return 1;
  } else if (fact > 50) {
    return 2;
  } else {
    return 0;
  }
}
