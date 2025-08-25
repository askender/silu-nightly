int gcd(int a, int b) {
  while (b != 0) {
    int temp = b;
    b = a % b;
    a = temp;
  }
  return a;
}

int factorial(int n) {
  if (n <= 1) {
    return 1;
  }

  int result = 1;
  int i;

  for (i = 2; i <= n; i++) {
    result *= i;
  }

  return result;
}

int fibonacci(int n) {
  if (n <= 0) {
    return 0;
  }
  if (n == 1) {
    return 1;
  }

  int a = 0;
  int b = 1;
  int temp;
  int count = 2;

  while (count <= n) {
    temp = a + b;
    a = b;
    b = temp;
    count++;
  }

  return b;
}

int is_prime(int n) {
  if (n <= 1) {
    return 0;
  }
  if (n <= 3) {
    return 1;
  }
  if (n % 2 == 0 || n % 3 == 0) {
    return 0;
  }

  int i;
  for (i = 5; i * i <= n; i += 6) {
    if (n % i == 0 || n % (i + 2) == 0) {
      return 0;
    }
  }

  return 1;
}

int array_sum(int arr[], int size) {
  int sum = 0;
  int i;

  for (i = 0; i < size; i++) {
    sum += arr[i];
  }

  return sum;
}

int array_max(int arr[], int size) {
  if (size <= 0) {
    return 0;
  }

  int max_val = arr[0];
  int i;

  for (i = 1; i < size; i++) {
    if (arr[i] > max_val) {
      max_val = arr[i];
    }
  }

  return max_val;
}

int binary_search(int arr[], int size, int target) {
  int left = 0;
  int right = size - 1;

  while (left <= right) {
    int mid = left + (right - left) / 2;

    if (arr[mid] == target) {
      return mid;
    } else if (arr[mid] < target) {
      left = mid + 1;
    } else {
      right = mid - 1;
    }
  }

  return -1;
}

int power(int base, int exp) {
  if (exp == 0) {
    return 1;
  }

  int result = 1;

  while (exp > 0) {
    if (exp % 2 == 1) {
      result *= base;
    }
    base *= base;
    exp /= 2;
  }

  return result;
}

int count_digits(int n) {
  if (n == 0) {
    return 1;
  }

  int count = 0;
  if (n < 0) {
    n = -n;
  }

  while (n > 0) {
    count++;
    n /= 10;
  }

  return count;
}

int reverse_number(int n) {
  int reversed = 0;
  int sign = 1;

  if (n < 0) {
    sign = -1;
    n = -n;
  }

  while (n > 0) {
    reversed = reversed * 10 + n % 10;
    n /= 10;
  }

  return reversed * sign;
}

int main() {
  int a = 48;
  int b = 18;

  int gcd_result = gcd(a, b);

  int fact_5 = factorial(5);

  int fib_10 = fibonacci(10);

  int prime_check = is_prime(17);

  int numbers[5];
  numbers[0] = 10;
  numbers[1] = 20;
  numbers[2] = 30;
  numbers[3] = 40;
  numbers[4] = 50;

  int sum = array_sum(numbers, 5);
  int max_num = array_max(numbers, 5);

  int sorted_array[6];
  sorted_array[0] = 1;
  sorted_array[1] = 3;
  sorted_array[2] = 5;
  sorted_array[3] = 7;
  sorted_array[4] = 9;
  sorted_array[5] = 11;

  int search_result = binary_search(sorted_array, 6, 7);

  int power_result = power(2, 8);

  int digit_count = count_digits(12345);

  int reversed = reverse_number(12345);

  int final_result = gcd_result + fact_5 + fib_10 + prime_check + sum +
                     max_num + search_result + power_result + digit_count +
                     reversed;

  if (final_result > 1000) {
    return 1;
  } else if (final_result > 500) {
    return 2;
  } else {
    return 0;
  }
}
