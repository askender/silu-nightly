// Simple demonstration of typedef support in C IR Generator
// This shows the basic typedef functionality requested

// 给 int 类型取别名 MyInt
typedef int MyInt;

// Additional examples of typedef usage
typedef float Real;
typedef char Character;
typedef int *IntPointer;

int main() {
  // Using the typedef alias MyInt instead of int
  MyInt number = 42;
  MyInt another = 100;

  // Using other typedefs
  Real pi = 3.14159;
  Character letter = 'A';

  // Arithmetic with typedef variables
  MyInt sum = number + another;

  // Using pointer typedef
  IntPointer ptr = &number;

  return sum;
}
