// Demonstration of struct typedef support in C IR Generator
// This shows the specific functionality that was requested

// 给 int 类型取别名 MyInt (basic typedef)
typedef int MyInt;

// 定义结构体 Person 并取别名 (struct typedef - the main requested feature)
typedef struct {
  char name[20];
  int age;
} Person;

// Additional struct typedef examples
typedef struct {
  int x;
  int y;
} Point;

typedef struct {
  Person person;
  Point location;
  MyInt employee_id;
} Employee;

int main() {
  // Using basic typedef
  MyInt number = 42;

  // Using struct typedef - the requested functionality
  Person p1;
  p1.age = 25;
  // p1.name would need strcpy in real C, but this shows the structure

  Person p2;
  p2.age = 30;

  // Using nested struct typedefs
  Point office_location;
  office_location.x = 100;
  office_location.y = 200;

  Employee emp;
  emp.person = p1;
  emp.location = office_location;
  emp.employee_id = number;

  // Calculations using struct fields
  MyInt total_age = p1.age + p2.age;
  MyInt area = office_location.x * office_location.y;

  return total_age + area;
}
