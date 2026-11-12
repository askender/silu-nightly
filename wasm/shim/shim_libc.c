/* shim_libc.c - freestanding wasm64 libc shim for the Silu compiler.
 *
 * The compiler .ll declares exactly these externals (26 at last count):
 *   allocator: malloc/calloc/realloc/free        (i64 sizes)
 *   strings:   strlen/memcmp/memchr + llvm.memcpy/memmove/memset
 *   formatted: printf/snprintf                   (variadic => must be
 *               in-module C; wasm cannot import/export variadic fns)
 *   parsing:   strtod/strtol                     (float/int literal lexing)
 *   files/in:  fopen/fread/fseek/ftell/fclose/getchar  (fixed arity =>
 *               JS host imports; virtual FS serves import expansion)
 *   misc:      exit, pow                         (JS host imports)
 * llvm.* intrinsics compile natively; llvm.floor/sqrt are wasm ops.
 * Linear-memory growth uses wasm builtins directly (no host import).
 *
 * Rule of the house: unsupported path => abort, never approximate.
 */

typedef unsigned int u32;
typedef unsigned long u64;
typedef long i64;

/* ---- host imports (fixed arity only; wasm cannot do varargs) ---- */
__attribute__((import_module("silu_host"), import_name("die")))
__attribute__((noreturn)) void host_die(const char *msg, u64 len);
__attribute__((import_module("silu_host"), import_name("write")))
void host_write(int fd, const char *buf, u64 len);
__attribute__((import_module("silu_host"), import_name("fmt_double")))
u64 host_fmt_double(char *buf, u64 cap, double v, int spec, int prec);
__attribute__((import_module("silu_host"), import_name("strtod")))
double host_strtod(const char *s, u64 len, u64 *consumed);
__attribute__((import_module("silu_host"), import_name("getchar")))
int host_getchar(void);
__attribute__((import_module("silu_host"), import_name("pow")))
double pow(double a, double b);
__attribute__((import_module("silu_host"), import_name("file_open")))
i64 host_file_open(const char *path, u64 len);
__attribute__((import_module("silu_host"), import_name("file_read")))
i64 host_file_read(i64 id, void *dst, u64 len);
__attribute__((import_module("silu_host"), import_name("file_seek")))
i64 host_file_seek(i64 id, i64 off, int whence);
__attribute__((import_module("silu_host"), import_name("file_tell")))
i64 host_file_tell(i64 id);
__attribute__((import_module("silu_host"), import_name("file_close")))
int host_file_close(i64 id);
__attribute__((import_module("silu_host"), import_name("exit")))
__attribute__((noreturn)) void host_exit(int code);

void exit(int code) __attribute__((noreturn));

/* ---- panic ---- */
__attribute__((noreturn)) static void shim_die(const char *msg) {
    u64 n = 0;
    while (msg[n]) n++;
    host_die(msg, n);
    for (;;) {}
}

/* ---- allocator: first-fit over a dedicated free list ----
 * Block: {u64 size; u64 used; hdr *next; hdr *flink}. malloc touches
 * only free blocks - the compiler churns millions of allocations and an
 * all-blocks walk is quadratic. No coalescing: the free list recycles
 * blocks; fragmentation costs pages, not correctness (wasm64 memory
 * caps at 4GB). */

extern unsigned char __heap_base[];

#define ALIGN16(x) (((x) + 15) & ~(u64)15)
#define PAGE 65536

typedef struct hdr {
    u64 size;
    u64 used;
    struct hdr *next;  /* physical order, all blocks */
    struct hdr *flink; /* free-list next, valid when !used */
} hdr_t;

static hdr_t *free_head = 0;
static char *heap_top = 0;

void *malloc(u64 n) {
    if (n == 0) n = 1;
    n = ALIGN16(n);
    hdr_t **prev = &free_head;
    for (hdr_t *h = free_head; h; prev = &h->flink, h = h->flink) {
        if (h->size < n) continue;
        /* unlink from the free list */
        *prev = h->flink;
        if (h->size >= n + sizeof(hdr_t) + 32) {
            /* split: remainder stays a free block */
            hdr_t *rest = (hdr_t *)((char *)(h + 1) + n);
            rest->size = h->size - n - sizeof(hdr_t);
            rest->used = 0;
            rest->next = h->next;
            rest->flink = free_head;
            free_head = rest;
            h->next = rest;
            h->size = n;
        }
        h->used = 1;
        return (void *)(h + 1);
    }
    /* no fit: commit pages, add a fresh used block */
    if (heap_top == 0) heap_top = (char *)ALIGN16((u64)__heap_base);
    u64 need = sizeof(hdr_t) + n;
    u64 cur_bytes = __builtin_wasm_memory_size(0) * PAGE;
    u64 want_bytes = (u64)heap_top + need;
    if (want_bytes > cur_bytes) {
        u64 want_pages = (want_bytes + PAGE - 1) / PAGE;
        if (__builtin_wasm_memory_grow(0, (long)(want_pages - cur_bytes / PAGE)) < 0)
            shim_die("shim: OOM");
    }
    hdr_t *nh = (hdr_t *)heap_top;
    heap_top = (char *)ALIGN16(want_bytes);
    nh->size = n;
    nh->used = 1;
    nh->next = 0;
    return (void *)(nh + 1);
}

void free(void *p) {
    if (!p) return;
    hdr_t *h = (hdr_t *)p - 1;
    if (!h->used) shim_die("shim: double free");
    h->used = 0;
    h->flink = free_head;
    free_head = h;
}

void *calloc(u64 a, u64 b) {
    if (b != 0 && a > (u64)-1 / b) return 0;
    u64 n = a * b;
    char *p = malloc(n);
    for (u64 i = 0; i < n; i++) p[i] = 0;
    return p;
}

void *realloc(void *p, u64 n) {
    if (!p) return malloc(n);
    hdr_t *h = (hdr_t *)p - 1;
    u64 old = h->size;
    void *q = malloc(n);
    u64 c = n < old ? n : old;
    char *a = (char *)p, *b = (char *)q;
    for (u64 i = 0; i < c; i++) b[i] = a[i];
    free(p);
    return q;
}

/* ---- strings / memory ---- */

u64 strlen(const char *s) {
    u64 n = 0;
    while (s[n]) n++;
    return n;
}

int memcmp(const void *a, const void *b, u64 n) {
    const unsigned char *x = a, *y = b;
    for (u64 i = 0; i < n; i++)
        if (x[i] != y[i]) return x[i] < y[i] ? -1 : 1;
    return 0;
}

void *memchr(const void *s, int c, u64 n) {
    const unsigned char *x = s;
    for (u64 i = 0; i < n; i++)
        if (x[i] == (unsigned char)c) return (void *)(x + i);
    return 0;
}

void *memcpy(void *d, const void *s, u64 n) {
    unsigned char *dd = d;
    const unsigned char *ss = s;
    for (u64 i = 0; i < n; i++) dd[i] = ss[i];
    return d;
}

void *memmove(void *d, const void *s, u64 n) {
    unsigned char *dd = d;
    const unsigned char *ss = s;
    if ((u64)dd - (u64)ss >= n) {
        for (u64 i = 0; i < n; i++) dd[i] = ss[i];
    } else {
        for (u64 i = n; i-- > 0;) dd[i] = ss[i];
    }
    return d;
}

void *memset(void *d, int c, u64 n) {
    unsigned char *dd = d;
    for (u64 i = 0; i < n; i++) dd[i] = (unsigned char)c;
    return d;
}

/* ---- formatted output ----
 * Supported: %d %i %u %x %X %p %c %s %f %g %e %E %G with -/0 flags,
 * width, .prec, l/z/h no-ops. Anything else => abort. */

typedef struct {
    char *buf; /* 0 => count only */
    u64 cap;
    u64 n;
} out_t;

static void out_ch(out_t *o, char c) {
    if (o->buf) {
        if (o->n + 1 < o->cap) o->buf[o->n] = c;
    }
    o->n++;
}

static void out_str(out_t *o, const char *s, u64 len) {
    for (u64 i = 0; i < len; i++) out_ch(o, s[i]);
}

static void out_pad(out_t *o, char c, long k) {
    while (k-- > 0) out_ch(o, c);
}

static void fmt_u64(out_t *o, u64 v, int base, int upper) {
    char tmp[24];
    const char *dig = upper ? "0123456789ABCDEF" : "0123456789abcdef";
    int k = 0;
    do {
        tmp[k++] = dig[v % (u64)base];
        v /= (u64)base;
    } while (v);
    while (k-- > 0) out_ch(o, tmp[k]);
}

static void fmt_i64(out_t *o, i64 v, int base, int upper) {
    if (v < 0) {
        out_ch(o, '-');
        fmt_u64(o, (u64)(-(v + 1)) + 1, base, upper);
    } else {
        fmt_u64(o, (u64)v, base, upper);
    }
}

static void fmt_f64(out_t *o, double v, char spec, int prec) {
    char tmp[420];
    if (prec < 0) prec = 6;
    u64 k = host_fmt_double(tmp, sizeof tmp, v, (int)spec, prec);
    if (k == (u64)-1) shim_die("shim: fmt_double overflow");
    out_str(o, tmp, k);
}

typedef __builtin_va_list va_list;
#define va_start(ap, last) __builtin_va_start(ap, last)
#define va_end(ap) __builtin_va_end(ap)
#define va_arg(ap, ty) __builtin_va_arg(ap, ty)

static void vformat(out_t *o, const char *f, va_list ap) {
    for (; *f; f++) {
        if (*f != '%') {
            out_ch(o, *f);
            continue;
        }
        f++;
        int zero_pad = 0, left = 0;
        for (; *f; f++) {
            if (*f == '-') left = 1;
            else if (*f == '0') zero_pad = 1;
            else break;
        }
        long width = -1;
        if (*f == '*') {
            width = va_arg(ap, int);
            f++;
        } else if (*f >= '1' && *f <= '9') {
            width = 0;
            while (*f >= '0' && *f <= '9') width = width * 10 + (*f++ - '0');
        }
        int prec = -1;
        if (*f == '.') {
            f++;
            if (*f == '*') {
                prec = va_arg(ap, int);
                f++;
            } else {
                prec = 0;
                while (*f >= '0' && *f <= '9') prec = prec * 10 + (*f++ - '0');
            }
        }
        while (*f == 'l' || *f == 'z' || *f == 'h') f++;
        char spec = *f;
        if (!spec) break;
        char tmp[420];
        out_t one;
        one.buf = tmp;
        one.cap = sizeof tmp;
        one.n = 0;
        int need_pad = 1;
        switch (spec) {
        case 'd':
        case 'i':
            fmt_i64(&one, va_arg(ap, i64), 10, 0);
            break;
        case 'u':
            fmt_u64(&one, va_arg(ap, u64), 10, 0);
            break;
        case 'x':
        case 'X':
            fmt_u64(&one, va_arg(ap, u64), 16, spec == 'X');
            break;
        case 'p':
            out_str(&one, "0x", 2);
            fmt_u64(&one, (u64)va_arg(ap, void *), 16, 0);
            break;
        case 'c':
            tmp[0] = (char)va_arg(ap, int);
            one.n = 1;
            break;
        case 's': {
            const char *s = va_arg(ap, const char *);
            u64 len = s ? strlen(s) : 0;
            if (prec >= 0 && (u64)prec < len) len = (u64)prec;
            long w = width - (long)len;
            if (!left && w > 0) out_pad(o, ' ', w);
            out_str(o, s, len);
            if (left && w > 0) out_pad(o, ' ', w);
            need_pad = 0;
            break;
        }
        case 'f':
        case 'g':
        case 'e':
        case 'G':
        case 'E': {
            double v = va_arg(ap, double);
            char fb[420];
            if (prec < 0) prec = 6;
            u64 k = host_fmt_double(fb, sizeof fb, v, (int)spec, prec);
            if (k == (u64)-1) shim_die("shim: fmt_double overflow");
            long w = width - (long)k;
            if (!left && w > 0) out_pad(o, zero_pad ? '0' : ' ', w);
            out_str(o, fb, k);
            if (left && w > 0) out_pad(o, ' ', w);
            need_pad = 0;
            break;
        }
        case '%':
            out_ch(o, '%');
            need_pad = 0;
            break;
        default:
            shim_die("shim: unsupported printf specifier");
        }
        if (need_pad) {
            long w = width - (long)one.n;
            if (!left && w > 0) out_pad(o, zero_pad ? '0' : ' ', w);
            for (u64 i = 0; i < one.n; i++) out_ch(o, tmp[i]);
            if (left && w > 0) out_pad(o, ' ', w);
        }
    }
}

int printf(const char *f, ...) {
    out_t o;
    o.buf = 0;
    o.cap = 0;
    o.n = 0;
    va_list ap;
    va_start(ap, f);
    vformat(&o, f, ap);
    va_end(ap);
    char *b = malloc(o.n ? o.n : 1);
    out_t o2;
    o2.buf = b;
    o2.cap = o.n + 1;
    o2.n = 0;
    va_start(ap, f);
    vformat(&o2, f, ap);
    va_end(ap);
    host_write(1, b, o2.n);
    return (int)o2.n;
}

int snprintf(char *dst, u64 cap, const char *f, ...) {
    out_t o;
    o.buf = dst;
    o.cap = cap;
    o.n = 0;
    va_list ap;
    va_start(ap, f);
    vformat(&o, f, ap);
    va_end(ap);
    if (cap) {
        if (o.n < cap) dst[o.n] = 0;
        else dst[cap - 1] = 0;
    }
    return (int)o.n;
}

/* ---- parsing ---- */

long strtol(const char *s, char **end, int base) {
    u64 i = 0;
    while (s[i] == ' ' || s[i] == '\t' || s[i] == '\n' || s[i] == '\r') i++;
    int neg = 0;
    if (s[i] == '+' || s[i] == '-') neg = (s[i] == '-'), i++;
    if ((base == 0 || base == 16) && s[i] == '0' &&
        (s[i + 1] == 'x' || s[i + 1] == 'X')) {
        base = 16;
        i += 2;
    } else if (base == 0) {
        base = s[i] == '0' ? 8 : 10;
    }
    u64 v = 0;
    for (;; i++) {
        int d;
        char c = s[i];
        if (c >= '0' && c <= '9') d = c - '0';
        else if (c >= 'a' && c <= 'f') d = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') d = c - 'A' + 10;
        else break;
        if (d >= base) break;
        v = v * (u64)base + (u64)d;
    }
    if (end) *end = (char *)(s + i);
    return neg ? -(long)v : (long)v;
}

double strtod(const char *s, char **end) {
    u64 consumed = 0;
    double v = host_strtod(s, strlen(s), &consumed);
    if (end) *end = (char *)(s + consumed);
    return v;
}

int getchar(void) { return host_getchar(); }

/* ---- helpers the wasm backend / optimizer introduce ----
 * putchar: printf("%c")-pattern folding. fmod: llvm.fmod.f64 lowered to
 * the libm call on wasm. __multi3: the i128 multiply helper (wasm has no
 * i128 multiply; the datalayout text constant drags the type in). */

int putchar(int c) {
    char b = (char)c;
    host_write(1, &b, 1);
    return (unsigned char)c;
}

/* exact fmod: subtract aligned doubles (Sterbenz-exact each step) */
double fmod(double x, double y) {
    if (x != x || y != y) return x + y;
    if (y == 0.0) return (x * 0.0) / (x * 0.0); /* invalid -> NaN */
    if (__builtin_isinf(x)) return (x * 0.0) / (y * 0.0);
    if (__builtin_isinf(y)) return x;
    if (x == 0.0) return x;
    int sx = __builtin_signbit(x);
    double ax = __builtin_fabs(x), ay = __builtin_fabs(y);
    while (ax >= ay) {
        double t = ay;
        while (t + t <= ax) t += t;
        ax -= t; /* exact: t <= ax <= 2t */
    }
    return sx ? -ax : ax;
}

typedef unsigned __int128 u128;

/* optnone: at -O2 instcombine re-widens the 32-bit-limb multiply shape
 * back into an i128 multiply, which lowers to a __multi3 call - these
 * bodies must stay unoptimized or they recurse into themselves */
__attribute__((optnone)) static u64 mulhi64(u64 x, u64 y) {
    /* high 64 bits of x*y via 32-bit limbs (no i128 multiply) */
    u32 x0 = (u32)x, x1 = (u32)(x >> 32);
    u32 y0 = (u32)y, y1 = (u32)(y >> 32);
    u64 p0 = (u64)x0 * y0;
    u64 p1 = (u64)x0 * y1;
    u64 p2 = (u64)x1 * y0;
    u64 p3 = (u64)x1 * y1;
    u64 mid = (p0 >> 32) + (u32)p1 + (u32)p2;
    return p3 + (p1 >> 32) + (p2 >> 32) + (mid >> 32);
}

__attribute__((optnone)) u128 __multi3(u128 a, u128 b) {
    u64 a0 = (u64)a, a1 = (u64)(a >> 64);
    u64 b0 = (u64)b, b1 = (u64)(b >> 64);
    u64 lo = a0 * b0;
    u64 hi = mulhi64(a0, b0) + a1 * b0 + a0 * b1;
    return ((u128)hi << 64) | lo;
}

/* ---- files: JS host owns the virtual FS; FILE* is an id disguised ----
 * FILE* = id*8+4 so it stays non-null. */

void *fopen(const char *path, const char *mode) {
    (void)mode; /* the compiler only reads */
    i64 id = host_file_open(path, strlen(path));
    if (id < 0) return 0;
    return (void *)(u64)(id * 8 + 4);
}

u64 fread(void *dst, u64 sz, u64 n, void *f) {
    if (sz != 1) shim_die("shim: fread with size!=1");
    i64 got = host_file_read(((u64)f - 4) / 8, dst, n);
    return got < 0 ? 0 : (u64)got;
}

int fseek(void *f, i64 off, int whence) {
    return (int)host_file_seek(((u64)f - 4) / 8, off, whence);
}

i64 ftell(void *f) { return host_file_tell(((u64)f - 4) / 8); }

int fclose(void *f) { return host_file_close(((u64)f - 4) / 8); }

void exit(int code) { host_exit(code); }
