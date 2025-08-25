# test out-of-memory with malloc

l = list(range(1000))
1000000000 * l

# test out-of-memory with realloc
[].extend(range(1000000000))
