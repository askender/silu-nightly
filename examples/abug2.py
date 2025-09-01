# test out-of-memory with malloc

alist = list(range(1000))
1000000000 * alist

# test out-of-memory with realloc
[].extend(range(1000000000))
