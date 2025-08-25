
float float_branch(float x, float y) {
  float result = 0.0;

  if (x > 0.0)
    result += x * y;
  else
    result -= x * y;

  if (y == 0.0)
    result = 100.0;

  if (result > 50.0)
    result = 999.0;

  return result;
}
