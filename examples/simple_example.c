/*
 * Simple C program for testing IR generation
 * This file contains various C constructs without preprocessor directives
 */

// Simple function with arithmetic
int add(int a, int b) {
  int result = a + b;
  return result;
}

// Function with control flow
int max(int a, int b) {
  if (a > b) {
    return a;
  } else {
    return b;
  }
}

// Function with loops
int factorial(int n) {
  int result = 1;
  int i;

  for (i = 1; i <= n; i++) {
    result = result * i;
  }

  return result;
}

// Function with while loop
int fibonacci(int n) {
  int a = 0, b = 1, temp;
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

// Function with array operations
int sum_array(int arr[], int size) {
  int sum = 0;
  int i;

  for (i = 0; i < size; i++) {
    sum += arr[i];
  }

  return sum;
}

// Main function with various operations
int main() {
  int x = 10;
  int y = 20;
  int z;

  // Simple arithmetic
  z = add(x, y);

  // Control flow
  int maximum = max(x, y);

  // Loop calculation
  int fact = factorial(5);

  // Conditional with multiple branches
  if (fact > 100) {
    return 1;
  } else if (fact > 50) {
    return 2;
  } else {
    return 0;
  }
}
