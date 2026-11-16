/*
 * siluc - the one-command Silu driver (rustc-shaped).
 *
 *     siluc file.si -o prog
 *
 * Pipeline: siluc1 (the native self-hosted compiler, fe + converter
 * inlined) produces the full .ll on stdout; the driver splits off the
 * shared ~350KB runtime prefix (compiled once into a cached .o),
 * synthesizes the external declarations the user part needs, then
 * clang compiles the ~KB user part and links against the cached
 * runtime as LTO bitcode (-flto -O2 at link time lets the runtime
 * inline into hot loops: spectral 4.4ms -> 3.5ms, +20ms link)
 * runtime object. No Python anywhere.
 *
 * Cache layout (~/.cache/silu-runtime/driver/):
 *   rt.ll    - the runtime prefix text (the converter emits it as a
 *              strict prefix of every program; rebuilt when missing)
 *   rt.syms  - "kind\\tret-or-type\\tname" lines for every runtime
 *              symbol (for declaration synthesis)
 *   rt.o     - the compiled runtime object
 */

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/select.h>
#include <time.h>
#include <signal.h>
#include <libgen.h>
#ifdef __APPLE__
#include <mach-o/dyld.h>
#endif
#include <fcntl.h>

#define MAX_LL (64 * 1024 * 1024)
#define MAX_SYMS 4096
#define LINE 8192

static char g_exe_dir[4096];
static char g_cache_dir[4096];
static int g_conn_fd = -1; /* daemon request socket, -1 when not serving */
static int g_dbg_fd = -1;  /* the daemon's original stderr, for post-dup2 logging */
static int g_err_capture_fd = -1; /* request child's captured stderr */
static int g_serving_child = 0; /* a request child: no atexit teardown */

static void die(const char *msg);

static void make_cache_dirs(const char *path) {
    char partial[4096];
    size_t n = strlen(path);
    if (n >= sizeof partial) die("cache path too long");
    memcpy(partial, path, n + 1);
    for (char *p = partial + 1; *p; p++) {
        if (*p == '/') {
            *p = 0;
            if (mkdir(partial, 0755) != 0 && errno != EEXIST) die("creating cache directory");
            *p = '/';
        }
    }
    if (mkdir(partial, 0755) != 0 && errno != EEXIST) die("creating cache directory");
}

static void die(const char *msg) {
    fprintf(stderr, "siluc: %s\n", msg);
    if (g_conn_fd >= 0) {
        /* serving a daemon request: die() fires INSIDE run_compile, so
           the post-compile diagnostic streaming never runs - stream the
           captured stderr here, then close the protocol with the
           failure line (review S6) */
        if (g_err_capture_fd >= 0) {
            lseek(g_err_capture_fd, 0, SEEK_SET);
            char dbuf[8192];
            ssize_t dn;
            while ((dn = read(g_err_capture_fd, dbuf, sizeof dbuf)) > 0) {
                if (write(g_conn_fd, dbuf, (size_t)dn) < 0) break;
            }
        }
        dprintf(g_conn_fd, "ERR %s\n", msg);
    }
    exit(1);
}

static char *read_all(const char *path, long *out_len) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = malloc(len + 1);
    if (fread(buf, 1, len, f) != (size_t)len) { fclose(f); free(buf); return NULL; }
    fclose(f);
    buf[len] = 0;
    if (out_len) *out_len = len;
    return buf;
}

static int run_capture(const char *argv[], const char *stdin_path,
                       char **out, long *out_len) {
    int in_pipe[2], out_pipe[2];
    if (pipe(in_pipe) || pipe(out_pipe)) die("pipe");
    pid_t pid = fork();
    if (pid < 0) die("fork");
    if (pid == 0) {
        dup2(in_pipe[0], 0);
        dup2(out_pipe[1], 1);
        close(in_pipe[0]); close(in_pipe[1]);
        close(out_pipe[0]); close(out_pipe[1]);
        execvp(argv[0], (char *const *)argv);
        _exit(127);
    }
    close(in_pipe[0]); close(out_pipe[1]);
    if (stdin_path) {
        FILE *src = fopen(stdin_path, "rb");
        if (!src) { close(in_pipe[1]); close(out_pipe[0]); die("open stdin source"); }
        char buf[65536];
        size_t n;
        while ((n = fread(buf, 1, sizeof buf, src)) > 0)
            if (write(in_pipe[1], buf, n) < 0) break;
        fclose(src);
    } else {
        const char *empty = "";
        write(in_pipe[1], empty, 0);
    }
    close(in_pipe[1]);
    long cap = 1 << 20, len = 0;
    char *buf = malloc(cap);
    ssize_t n;
    while ((n = read(out_pipe[0], buf + len, cap - len)) > 0) {
        len += n;
        if (len == cap) { cap *= 2; buf = realloc(buf, cap); }
    }
    close(out_pipe[0]);
    int status;
    waitpid(pid, &status, 0);
    buf[len] = 0;
    *out = buf;
    if (out_len) *out_len = len;
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}

static const char *g_last_fail_cmd = NULL;

static int run_quiet(const char *argv[]) {
    pid_t pid = fork();
    if (pid < 0) die("fork");
    if (pid == 0) {
        int devnull = open("/dev/null", 1 /*O_WRONLY*/);
        dup2(devnull, 1);
        /* surface the child's stderr on failure paths: diagnostics
           were being swallowed wholesale (a link error gave only
           "link failed" with no cause) */
        execvp(argv[0], (char *const *)argv);
        _exit(127);
    }
    int status;
    waitpid(pid, &status, 0);
    int rc = WIFEXITED(status) ? WEXITSTATUS(status) : 1;
    if (rc != 0) {
        g_last_fail_cmd = argv[0];
        fprintf(stderr, "siluc: %s step failed (rc=%d):", argv[0], rc);
        for (const char **a = argv + 1; *a; a++)
            fprintf(stderr, " %s", *a);
        fprintf(stderr, "\n");
    }
    return rc;
}

/* ---------- runtime prefix split + declaration synthesis ---------- */

typedef struct {
    char kind;            /* 'f' function, 'g' global */
    char sig[LINE];       /* full define-line text or global type */
    char name[256];
} Sym;

static Sym g_syms[MAX_SYMS];
static int g_nsyms = 0;

/* The LTO cache is compiler-identity sensitive: bitcode from a
   different clang (a conda env's LLVM vs Apple's) cannot be read by
   this linker's libLTO. rt.clang stamps the builder's --version
   line; a mismatch rebuilds the cache with the current clang. */
static void write_clang_stamp(const char *dir) {
    char stamp[4096];
    snprintf(stamp, sizeof stamp, "%s/rt.clang", dir);
    FILE *f = fopen(stamp, "w");
    if (!f) return;
    const char *argv[] = { "clang", "--version", NULL };
    char *out = NULL;
    if (run_capture(argv, NULL, &out, NULL) == 0 && out) {
        const char *nl = strchr(out, '\n');
        size_t n = nl ? (size_t)(nl - out) : strlen(out);
        fwrite(out, 1, n, f);
        fputc('\n', f);
    }
    fclose(f);
}

static int clang_stamp_matches(const char *dir) {
    char stamp[4096], cur[512];
    snprintf(stamp, sizeof stamp, "%s/rt.clang", dir);
    FILE *f = fopen(stamp, "r");
    if (!f) return 0;
    size_t n = fread(cur, 1, sizeof cur - 1, f);
    fclose(f);
    cur[n] = 0;
    if (n == 0) return 0;
    const char *argv[] = { "clang", "--version", NULL };
    char *out = NULL;
    if (run_capture(argv, NULL, &out, NULL) != 0 || !out) return 0;
    size_t m = strlen(cur);
    int ok = strncmp(out, cur, m) == 0;
    return ok;
}

static void parse_runtime_symbols(const char *rt_ll) {
    g_nsyms = 0;
    const char *p = rt_ll;
    while (*p && g_nsyms < MAX_SYMS) {
        const char *eol = strchr(p, '\n');
        if (!eol) break;
        size_t len = eol - p;
        if (len >= 7 && strncmp(p, "define ", 7) == 0) {
            /* define <ret> @"name"( ... */
            const char *at = strstr(p, "@\"");
            if (at && at < eol) {
                Sym *s = &g_syms[g_nsyms++];
                s->kind = 'f';
                size_t siglen = len < LINE - 1 ? len : LINE - 1;
                memcpy(s->sig, p, siglen);
                s->sig[siglen] = 0;
                const char *nm = at + 2;
                const char *close = strchr(nm, '"');
                size_t nmlen = close - nm;
                if (nmlen > 255) nmlen = 255;
                memcpy(s->name, nm, nmlen);
                s->name[nmlen] = 0;
            }
        } else if (len >= 2 && p[0] == '@' && p[1] == '"') {
            /* @"name" = [internal] (global|constant) <type> ...
               Since P6/P2 every string constant is `constant`, and
               interning lets the USER part reference prefix constants
               by the same name - they must synthesize an
               `external constant` declaration, not `external global`. */
            const char *eq = strstr(p, "= ");
            if (eq && eq < eol) {
                /* both keywords must be searched WITHIN this line:
                   strstr runs to end-of-buffer, a miss would otherwise
                   latch onto a later line's keyword and (via the
                   kp < eol guard) silently drop this symbol */
                const char *cp = strstr(eq, "constant ");
                if (cp && cp >= eol) cp = NULL;
                const char *gp = strstr(eq, "global ");
                if (gp && gp >= eol) gp = NULL;
                const char *kp = cp ? cp : gp;
                if (kp && kp < eol) {
                    Sym *s = &g_syms[g_nsyms++];
                    s->kind = cp ? 'c' : 'g';
                    const char *nm = p + 2;
                    const char *close = strchr(nm, '"');
                    size_t nmlen = close - nm;
                    if (nmlen > 255) nmlen = 255;
                    memcpy(s->name, nm, nmlen);
                    s->name[nmlen] = 0;
                    /* type text after the keyword ("constant " = 9
                       chars, "global " = 7). Bracketed types run to
                       the MATCHING close - struct types like
                       {i32, i8*} contain commas, so the comma cut may
                       only apply to scalars; the initializer after
                       the brackets (c"...") must not leak either. */
                    const char *t = kp + (cp ? 9 : 7);
                    const char *tend = eol;
                    if (*t == '[' || *t == '{') {
                        int depth = 0;
                        for (const char *q = t; q < tend; q++) {
                            if (*q == '[' || *q == '{') depth++;
                            else if (*q == ']' || *q == '}') {
                                if (--depth == 0) { tend = q + 1; break; }
                            }
                        }
                    } else {
                        const char *comma = strchr(t, ',');
                        if (comma && comma < tend) tend = comma;
                        const char *sp = strchr(t, ' ');
                        if (sp && sp < tend) tend = sp;
                    }
                    size_t tl = tend - t;
                    if (tl > LINE - 1) tl = LINE - 1;
                    memcpy(s->sig, t, tl);
                    s->sig[tl] = 0;
                }
            }
        }
        p = eol + 1;
    }
}

static const Sym *find_sym(const char *name, size_t len) {
    for (int i = 0; i < g_nsyms; i++)
        if (strlen(g_syms[i].name) == len &&
            memcmp(g_syms[i].name, name, len) == 0)
            return &g_syms[i];
    return NULL;
}

/* does the user body define this symbol itself? */
/* user-defined symbol set: one pass over the body collects every
   @"name" that IS a definition (a define line's function name or a
   global with '='), membership is then O(1). The previous per-
   reference full-body scan was O(refs x body) - ~570s on the 17MB
   self-host .ll, dwarfing every clang stage. */
#define UDEF_CAP (1 << 18)
static const char *udef_key[UDEF_CAP];
static size_t udef_len[UDEF_CAP];

static unsigned udef_hash(const char *s, size_t len) {
    unsigned h = 2166136261u;
    for (size_t i = 0; i < len; i++) { h ^= (unsigned char)s[i]; h *= 16777619u; }
    return h;
}

static void udef_add(const char *s, size_t len) {
    if (len == 0 || len > 255) return;
    unsigned i = udef_hash(s, len) & (UDEF_CAP - 1);
    while (udef_key[i]) {
        if (udef_len[i] == len && strncmp(udef_key[i], s, len) == 0) return;
        i = (i + 1) & (UDEF_CAP - 1);
    }
    udef_key[i] = s; udef_len[i] = len;
}

static int udef_has(const char *s, size_t len) {
    unsigned i = udef_hash(s, len) & (UDEF_CAP - 1);
    while (udef_key[i]) {
        if (udef_len[i] == len && strncmp(udef_key[i], s, len) == 0) return 1;
        i = (i + 1) & (UDEF_CAP - 1);
    }
    return 0;
}

static void udef_collect(const char *body) {
    const char *p = body;
    while ((p = strstr(p, "@\"")) != NULL) {
        const char *nm = p + 2;
        const char *close = strchr(nm, '"');
        if (!close) break;
        const char *bol = p;
        while (bol > body && bol[-1] != '\n') bol--;
        int is_def = 0;
        if (bol[0] == 'd' && (size_t)(p - bol) >= 7 &&
            strncmp(bol, "define ", 7) == 0)
            is_def = 1;
        else {
            const char *after = close + 1;
            while (*after == ' ') after++;
            if (*after == '=') is_def = 1;
        }
        if (is_def) udef_add(nm, (size_t)(close - nm));
        p = close;
    }
}

static int g_object_mode = 0;
static int g_no_lto = 0;

/* map an LLVM type token to the C type for the header */
static const char *c_type_of(const char *ll_ty) {
    if (strcmp(ll_ty, "i64") == 0) return "int64_t";
    if (strcmp(ll_ty, "double") == 0) return "double";
    if (strcmp(ll_ty, "i1") == 0) return "bool";
    if (strcmp(ll_ty, "i8*") == 0) return "const char*";
    return "void*"; /* pyobj and raw structs pass as opaque */
}

static int run_compile(int argc, char **argv) {
    const char *src = NULL, *out = NULL;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-o") == 0 && i + 1 < argc) out = argv[++i];
        else if (strcmp(argv[i], "--object") == 0) g_object_mode = 1;
        else if (strcmp(argv[i], "--no-lto") == 0) g_no_lto = 1;
        else if (argv[i][0] != '-') src = argv[i];
    }
    if (!src || !out) {
        fprintf(stderr, "usage: siluc file.si -o output [--object] [--no-lto]\n");
        return 2;
    }

    /* locate siluc1 next to this driver */
    ssize_t n = readlink("/proc/self/exe", g_exe_dir, sizeof g_exe_dir);
    if (n < 0) {
        /* macOS */
#ifdef __APPLE__
        char tmp[4096];
        uint32_t sz = sizeof tmp;
        if (_NSGetExecutablePath(tmp, &sz) == 0) {
            strcpy(g_exe_dir, tmp);
            n = strlen(g_exe_dir);
        }
#endif
    }
    if (n < 0 || (size_t)n >= sizeof g_exe_dir) die("locating self");
    g_exe_dir[n] = 0;
    char *dir = dirname(g_exe_dir);
    char siluc1[4096];
    snprintf(siluc1, sizeof siluc1, "%s/siluc1", dir);

    make_cache_dirs(g_cache_dir);

    char rt_ll_path[4096], rt_o_path[4096], rt_syms_path[4096];
    snprintf(rt_ll_path, sizeof rt_ll_path, "%s/rt.ll", g_cache_dir);
    /* separate objects per link mode: LTO bitcode cannot link in a
       plain -O2 link and vice versa */
    char rt_nolto_path[4096];
    snprintf(rt_nolto_path, sizeof rt_nolto_path, "%s/rt-nolto.o", g_cache_dir);
    snprintf(rt_o_path, sizeof rt_o_path, "%s/%s", g_cache_dir,
             g_no_lto ? "rt-nolto.o" : "rt.o");
    snprintf(rt_syms_path, sizeof rt_syms_path, "%s/rt.syms", g_cache_dir);

    struct stat st;
    /* rt.o must PAIR with rt.ll: a --no-lto run refreshes rt.ll
       without touching rt.o, and a cache built by a different clang
       (e.g. a conda env's LLVM vs Apple's) produces bitcode the
       linker's libLTO cannot read. Both checks fold into have_rt. */
    struct stat st_ll, st_o;
    int have_rt = stat(rt_ll_path, &st_ll) == 0
        && stat(rt_o_path, &st_o) == 0
        && st_o.st_mtime >= st_ll.st_mtime
        && clang_stamp_matches(g_cache_dir);

    /* 1. compile: siluc1 < src > full.ll (cwd = src's dir for imports) */
    char *full_ll;
    long full_len;
    const char *siluc1_argv[] = { siluc1, NULL };
    char src_abs[4096];
    if (src[0] == '/') snprintf(src_abs, sizeof src_abs, "%s", src);
    else { if (!getcwd(src_abs, sizeof src_abs)) die("getcwd"); strncat(src_abs, "/", sizeof src_abs - strlen(src_abs) - 1); strncat(src_abs, src, sizeof src_abs - strlen(src_abs) - 1); }
    char src_dir[4096];
    snprintf(src_dir, sizeof src_dir, "%s", src_abs);
    char *d = dirname(src_dir);
    char src_dir_final[4096];
    snprintf(src_dir_final, sizeof src_dir_final, "%s", d);
    char oldcwd[4096];
    if (!getcwd(oldcwd, sizeof oldcwd)) die("getcwd");
    if (chdir(src_dir_final) != 0) die("chdir to source dir");
    const char *base = strrchr(src_abs, '/');
    base = base ? base + 1 : src_abs;
    int rc = run_capture(siluc1_argv, base, &full_ll, &full_len);
    chdir(oldcwd);
    if (rc != 0 || full_len == 0) die("siluc1 failed on the input");

    /* 2. runtime prefix: load cache, or rebuild it once */
    char *rt_ll = have_rt ? read_all(rt_ll_path, NULL) : NULL;
    if (!rt_ll || strncmp(full_ll, rt_ll, strlen(rt_ll)) != 0) {
        /* rebuild: an empty program (`pass`) makes siluc1 emit exactly
           the runtime prefix */
        const char *pass_path = "/tmp/.siluc_pass.si";
        FILE *f = fopen(pass_path, "w");
        if (!f) die("cannot write pass file");
        fputs("pass\n", f);
        fclose(f);
        const char *probe_argv[] = { siluc1, NULL };
        int prc = run_capture(probe_argv, pass_path, &rt_ll, NULL);
        unlink(pass_path);
        if (prc != 0) die("probing the runtime prefix failed");
        /* the probe program contributes an empty main() after the
           runtime - cut it, the prefix ends at the last runtime
           function's closing brace */
        {
            const char *m = strstr(rt_ll, "\ndefine i32 @\"main\"()");
            if (m) {
                long keep = m - rt_ll + 1; /* keep the final \n */
                rt_ll[keep] = 0;
            }
        }
        /* cache the RAW prefix (byte-identical to what every program
           emits, so the prefix check stays a plain memcmp) */
        FILE *rf = fopen(rt_ll_path, "w");
        if (!rf) die("cannot write rt.ll cache");
        fputs(rt_ll, rf);
        fclose(rf);
        have_rt = 0; /* force rt.o rebuild */
    }
    parse_runtime_symbols(rt_ll);

    long rt_len = strlen(rt_ll);
    if ((long)full_len < rt_len || strncmp(full_ll, rt_ll, rt_len) != 0)
        die("runtime prefix invariant violated");

    /* 3. rebuild rt.o when needed: internal globals cannot survive
          the module boundary, so clang sees a visibility-lifted copy */
    if (!have_rt) {
        char lifted_path[4096];
        snprintf(lifted_path, sizeof lifted_path, "%s/rt-lifted.ll", g_cache_dir);
        FILE *lf = fopen(lifted_path, "w");
        if (!lf) die("cannot write lifted rt");
        const char *a = rt_ll;
        const char *IG = "= internal global";
        size_t igl = strlen(IG);
        while (*a) {
            if (strncmp(a, IG, igl) == 0) {
                fputs("= global", lf);
                a += igl;
            } else fputc(*a++, lf);
        }
        fclose(lf);
        if (g_no_lto) {
            const char *c1[] = { "clang", "-O2", "-ffunction-sections", "-fdata-sections", "-c", lifted_path, "-o", rt_o_path, NULL };
            if (run_quiet(c1) != 0) die("clang failed on the runtime");
        } else {
            const char *c1[] = { "clang", "-O2", "-flto", "-ffunction-sections", "-fdata-sections", "-c", lifted_path, "-o", rt_o_path, NULL };
            if (run_quiet(c1) != 0) die("clang failed on the runtime");
        }
    }

    write_clang_stamp(g_cache_dir);

    /* 4. split user body (skip header lines before the first
          define/declare/@) and collect header declares */
    const char *fb = full_ll;
    const char *cursor = fb;
    while (*cursor) {
        if (strncmp(cursor, "define", 6) == 0 || *cursor == '@' ||
            strncmp(cursor, "declare", 7) == 0)
            break;
        cursor = strchr(cursor, '\n');
        if (!cursor) { cursor = fb + strlen(fb); break; }
        cursor++;
    }
    const char *body = fb + rt_len;

    /* header declares from the FULL text's header region */
    char header_decls[65536];
    header_decls[0] = 0;
    {
        const char *p = fb;
        while (p < fb + rt_len) {
            const char *eol = strchr(p, '\n');
            if (!eol) break;
            size_t len = eol - p;
            if (len >= 7 && strncmp(p, "declare", 7) == 0) {
                strncat(header_decls, p, len);
                strcat(header_decls, "\n");
            }
            p = eol + 1;
        }
        /* also the user region's own header (between rt end and first
           define) can carry declares */
        const char *q = body;
        while (*q) {
            if (strncmp(q, "define", 6) == 0 || *q == '@') break;
            const char *eol = strchr(q, '\n');
            if (!eol) break;
            size_t len = eol - q;
            if (len >= 7 && strncmp(q, "declare", 7) == 0) {
                strncat(header_decls, q, len);
                strcat(header_decls, "\n");
            }
            q = eol + 1;
        }
    }

    /* 5. synthesized declarations: every @"sym" the body references
          that the runtime defines and the body does not */
    udef_collect(body);
    char decls[262144];
    decls[0] = 0;
    {
        const char *p = body;
        while ((p = strstr(p, "@\"")) != NULL) {
            const char *nm = p + 2;
            const char *close = strchr(nm, '"');
            if (!close) break;
            size_t len = close - nm;
            const Sym *s = find_sym(nm, len);
            if (s && !udef_has(nm, len)) {
                char one[LINE + 300];
                if (s->kind == 'f') {
                    /* declare with the REAL signature: a vararg (...)
                       decl clashes with the runtime's fixed-signature
                       definition under Apple Clang 16. sig holds the
                       whole define line: "define [internal ]ret
                       @"name"(params)...". */
                    const char *rp = s->sig + 7;   /* skip "define " */
                    if (strncmp(rp, "internal ", 9) == 0) rp += 9;
                    const char *at = strstr(rp, " @\"");
                    const char *lp = at ? strchr(at, '(') : NULL;
                    const char *rparen = NULL;
                    if (lp) {
                        /* balanced-paren scan: a function-pointer
                           parameter nests parens in the signature */
                        int depth = 0;
                        for (const char *q = lp; *q && *q != '\n'; q++) {
                            if (*q == '(') depth++;
                            else if (*q == ')') {
                                depth--;
                                if (depth == 0) { rparen = q; break; }
                            }
                        }
                    }
                    if (at && at > rp && lp && rparen) {
                        char rbuf[LINE], pbuf[LINE];
                        size_t rl = at - rp, pl = rparen - lp + 1;
                        if (rl > LINE - 1) rl = LINE - 1;
                        if (pl > LINE - 1) pl = LINE - 1;
                        memcpy(rbuf, rp, rl); rbuf[rl] = 0;
                        memcpy(pbuf, lp, pl); pbuf[pl] = 0;
                        snprintf(one, sizeof one, "declare %s @\"%s\"%s\n",
                                 rbuf, s->name, pbuf);
                    } else {
                        continue;
                    }
                } else {
                    /* kind must round-trip the definition: constants
                       declare as `external constant` (see the parser
                       note above) */
                    snprintf(one, sizeof one, "@\"%s\" = external %s %s\n",
                             s->name, s->kind == 'c' ? "constant" : "global",
                             s->sig);
                }
                if (!strstr(decls, one))
                    strcat(decls, one);
            }
            p = close;
        }
    }

    /* 6. user .ll preserves the host target emitted by siluc1 */
    char user_ll_path[] = "/tmp/siluc_userXXXXXX.ll";
    int ufd = mkstemps(user_ll_path, 3);
    FILE *uf = ufd >= 0 ? fdopen(ufd, "w") : NULL;
    if (!uf) die("cannot create user .ll");
    const char *header_end = strstr(full_ll, "\ndefine ");
    const char *declare_end = strstr(full_ll, "\ndeclare ");
    const char *global_end = strstr(full_ll, "\n@");
    if (declare_end && (!header_end || declare_end < header_end)) header_end = declare_end;
    if (global_end && (!header_end || global_end < header_end)) header_end = global_end;
    if (!header_end || header_end > body) die("invalid module header");
    fwrite(full_ll, 1, header_end - full_ll + 1, uf);
    fputc('\n', uf);
    if (header_decls[0]) { fputs(header_decls, uf); fputc('\n', uf); }
    if (decls[0]) { fputs(decls, uf); fputc('\n', uf); }
    fputs(body, uf);
    fclose(uf);

    if (g_object_mode) {
        /* library mode: rename main away, compile the WHOLE module
           (runtime included) as one .o, and generate a C header from
           the exported (external-linkage) function signatures */
        char obj_ll[4096];
        snprintf(obj_ll, sizeof obj_ll, "%s.obj.ll", out);
        FILE *mf = fopen(obj_ll, "w");
        if (!mf) die("cannot write obj .ll");
        const char *MP = "define i32 @\"main\"()";
        const char *mp = strstr(full_ll, MP);
        if (mp) {
            long head = mp - full_ll;
            fwrite(full_ll, 1, head, mf);
            const char *rest = strstr(mp, "\n}") ;
            rest = rest ? rest + 2 : mp + strlen(mp);
            fputs(rest, mf);
        } else {
            fputs(full_ll, mf);
        }
        fclose(mf);
        const char *co[] = { "clang", "-O2", "-fPIC", "-c", obj_ll, "-o", out, NULL };
        if (run_quiet(co) != 0) die("clang failed on the object module");
        unlink(obj_ll);

        /* header: scan for external define lines (no 'internal') */
        char h_path[4096];
        /* out may lack an extension; replace/append .h */
        snprintf(h_path, sizeof h_path, "%s.h", out);
        FILE *hf = fopen(h_path, "w");
        if (!hf) die("cannot write header");
        fprintf(hf, "/* generated by siluc --object */\n");
        fprintf(hf, "#include <stdint.h>\n#include <stdbool.h>\n\n");
        fprintf(hf, "typedef struct { int32_t tag; void* data; } PObj;\n\n");
        const char *p = full_ll;
        int n_exp = 0;
        while ((p = strstr(p, "define ")) != NULL) {
            const char *eol = strchr(p, '\n');
            if (!eol) break;
            if (strncmp(p, "define internal", 15) != 0) {
                /* parse: define <ret> @"name"(<ty> %.., ...) */
                char ret[128] = "void", name[256] = "";
                char params[2048] = "";
                const char *at = strstr(p, "@\"");
                if (at && at < eol) {
                    const char *nm = at + 2;
                    const char *close = strchr(nm, '"');
                    size_t nl2 = close - nm;
                    if (nl2 > 255) nl2 = 255;
                    memcpy(name, nm, nl2);
                    name[nl2] = 0;
                    const char *rp = p + 7;
                    size_t rl = at - rp;
                    while (rl > 0 && rp[rl-1] == ' ') rl--;
                    if (rl > 127) rl = 127;
                    memcpy(ret, rp, rl);
                    ret[rl] = 0;
                    /* params: split on commas, map each type token */
                    const char *lp = strchr(close, '(');
                    const char *rp2 = eol; /* stop at line end; multi-line sigs use ...) */
                    if (lp && lp < eol) {
                        const char *pp = lp + 1;
                        char *po = params;
                        *po = 0;
                        while (pp < rp2) {
                            while (*pp == ' ') pp++;
                            const char *tok = pp;
                            while (*pp && *pp != ',' && *pp != ')' && *pp != ' ' && *pp != '%') pp++;
                            size_t tl2 = pp - tok;
                            char tbuf[128];
                            if (tl2 > 127) tl2 = 127;
                            memcpy(tbuf, tok, tl2);
                            tbuf[tl2] = 0;
                            if (tl2 > 0) {
                                const char *ct = c_type_of(tbuf);
                                size_t cl = strlen(ct);
                                if (po + cl + 3 < params + sizeof params) {
                                    if (po != params) { *po++ = ','; *po++ = ' '; }
                                    memcpy(po, ct, cl);
                                    po += cl;
                                }
                            }
                            while (*pp && *pp != ',') pp++;
                            if (*pp == ',') pp++;
                        }
                        *po = 0;
                    }
                    if (strcmp(name, "main") != 0) {
                        fprintf(hf, "%s %s(%s);\n",
                                c_type_of(ret), name, params);
                        n_exp++;
                    }
                }
            }
            p = eol;
        }
        fclose(hf);
        if (n_exp == 0)
            fprintf(stderr, "siluc: note: no @export functions found; header has only PObj\n");
        return 0;
    }

    /* 7. clang user + link. --no-lto: plain -O2 objects - the LTO link
          of a huge module dominates wall time (measured 567s LTO vs 5.4s
          plain on the 17MB self-host .ll); the trade is the runtime no
          longer inlines into the user's hot loops. */
    char user_o_path[] = "/tmp/siluc_userXXXXXX.o";
    int ofd = mkstemps(user_o_path, 2);
    close(ofd);
    if (g_no_lto) {
        const char *c2[] = { "clang", "-O2", "-ffunction-sections", "-fdata-sections", "-c", user_ll_path, "-o", user_o_path, NULL };
        if (run_quiet(c2) != 0) die("clang failed on the user module");
#ifdef __APPLE__
        const char *c3[] = { "clang", "-O2", user_o_path, rt_o_path, "-o", out, "-lm", "-Wl,-dead_strip", NULL };
#else
        const char *c3[] = { "clang", "-O2", user_o_path, rt_o_path, "-o", out, "-lm", "-Wl,--gc-sections", NULL };
#endif
        if (run_quiet(c3) != 0) die("link failed");
    } else {
        if (full_len > 4 * 1024 * 1024)
            fprintf(stderr, "siluc: note: large module (%.1fMB .ll) - LTO "
                    "linking may take minutes; --no-lto links in seconds\n",
                    full_len / 1048576.0);
        const char *c2[] = { "clang", "-O2", "-flto", "-ffunction-sections", "-fdata-sections", "-c", user_ll_path, "-o", user_o_path, NULL };
        if (run_quiet(c2) != 0) die("clang failed on the user module");
#ifdef __APPLE__
        const char *c3[] = { "clang", "-flto", "-O2", user_o_path, rt_o_path, "-o", out, "-lm", "-Wl,-dead_strip", NULL };
#else
        const char *c3[] = { "clang", "-flto", "-O2", user_o_path, rt_o_path, "-o", out, "-lm", "-Wl,--gc-sections", NULL };
#endif
        if (run_quiet(c3) != 0) die("link failed");
    }

    unlink(user_ll_path);
    unlink(user_o_path);
    return 0;
}

/* ---------------- daemon mode ----------------
 *
 *     siluc --serve                       resident compile server
 *     SILUC_DAEMON=1 siluc file.si -o out forward to the server
 *
 * The daemon keeps the driver process warm and content-caches builds:
 * a request is "hash(source) out mtime" in <cache>/builds.log; a hit
 * whose output still exists and is at least as new as the recorded
 * build responds without compiling (~2ms vs ~160ms). Requests run in
 * forked children (fresh siluc1/clang state per build, same
 * concurrency properties as N direct siluc processes); a child's
 * stderr is wired to its client so compiler diagnostics stream live.
 * The direct path is untouched: without SILUC_DAEMON nothing changes.
 */

static void compute_cache_dir(void) {
    const char *home = getenv("HOME");
    const char *xdg = getenv("XDG_CACHE_HOME");
    if (xdg && *xdg)
        snprintf(g_cache_dir, sizeof g_cache_dir, "%s/silu-runtime/driver", xdg);
    else
        snprintf(g_cache_dir, sizeof g_cache_dir, "%s/.cache/silu-runtime/driver", home ? home : ".");
}

static unsigned long long fnv1a64_file(const char *path, int *ok) {
    FILE *f = fopen(path, "rb");
    if (!f) { *ok = 0; return 0; }
    unsigned long long h = 1469598103934665603ULL;
    char buf[65536];
    size_t n;
    *ok = 1;
    while ((n = fread(buf, 1, sizeof buf, f)) > 0) {
        for (size_t i = 0; i < n; i++) {
            h ^= (unsigned char)buf[i];
            h *= 1099511628211ULL;
        }
    }
    fclose(f);
    return h;
}

/* build-cache hit: hash matches, the output exists and is at least as
   new as the recorded build (an output overwritten by a later build
   of different source fails the mtime test) */
static int build_cache_hit(const char *hash, const char *out) {
    char log_path[4096];
    snprintf(log_path, sizeof log_path, "%s/builds.log", g_cache_dir);
    FILE *f = fopen(log_path, "r");
    if (!f) return 0;
    char line[8192];
    /* the LAST record for this out is authoritative: builds.log is
       append-only, so a later build from a DIFFERENT source leaves a
       newer record whose hash must win over an older same-hash line
       (review S1: the old mtime-only test served a stale binary) */
    char last_hash[32] = "";
    long last_mtime = 0;
    while (fgets(line, sizeof line, f)) {
        char lhash[32], lout[4096];
        long lmtime;
        if (sscanf(line, "%31s %ld %4095s", lhash, &lmtime, lout) != 3) continue;
        if (strcmp(lout, out) != 0) continue;
        snprintf(last_hash, sizeof last_hash, "%s", lhash);
        last_mtime = lmtime;
    }
    fclose(f);
    if (strcmp(last_hash, hash) != 0) return 0;
    struct stat st;
    return stat(out, &st) == 0 && (long)st.st_mtime >= last_mtime - 1;
}

static void build_cache_record(const char *hash, const char *out) {
    struct stat st;
    if (stat(out, &st) != 0) return;
    char log_path[4096];
    snprintf(log_path, sizeof log_path, "%s/builds.log", g_cache_dir);
    FILE *f = fopen(log_path, "a");
    if (!f) return;
    fprintf(f, "%s %ld %s\n", hash, (long)st.st_mtime, out);
    fclose(f);
}

static long now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long)(ts.tv_sec * 1000 + ts.tv_nsec / 1000000);
}

/* one request, in a forked child: parse "COMPILE <src> <out>", serve
   from the content cache or run the full pipeline in-process */
static void on_crash(int sig) {
    if (g_dbg_fd >= 0) dprintf(g_dbg_fd, "silucd: child crashed sig=%d\n", sig);
    if (g_conn_fd >= 0) dprintf(g_conn_fd, "ERR crashed sig=%d\n", sig);
    signal(sig, SIG_DFL);
    raise(sig);
}

static void serve_request(int conn) {
    g_conn_fd = conn;
    signal(SIGCHLD, SIG_DFL); /* run_compile's run_quiet needs waitpid */
    signal(SIGSEGV, on_crash);
    signal(SIGABRT, on_crash);
    signal(SIGBUS, on_crash);
    /* diagnostics are captured to a temp file and streamed BEFORE the
       verdict: sharing the connection fd with stderr let a client-side
       close turn the compile's stderr writes into silent breakage */
    g_serving_child = 1;
    char err_path[] = "/tmp/silucd_errXXXXXX";
    int err_fd = mkstemp(err_path);
    if (err_fd < 0) { dprintf(conn, "ERR mkstemp\n"); _exit(1); }
    unlink(err_path);
    g_err_capture_fd = err_fd;
    dup2(err_fd, 2);
    char req[8192];
    ssize_t got = read(conn, req, sizeof req - 1);
    if (got <= 0) _exit(1);
    req[got] = 0;
    char *nl = strchr(req, '\n');
    if (nl) *nl = 0;
    char cmd[16], src[4096], out[4096];
    if (sscanf(req, "%15s %4095s %4095s", cmd, src, out) != 3
            || strcmp(cmd, "COMPILE") != 0) {
        dprintf(conn, "ERR bad request\n");
        _exit(1);
    }
    long t0 = now_ms();
    int ok;
    unsigned long long hv = fnv1a64_file(src, &ok);

    if (!ok) {
        dprintf(conn, "ERR cannot read source\n");
        _exit(1);
    }
    char hash[32];
    snprintf(hash, sizeof hash, "%016llx", hv);
    if (build_cache_hit(hash, out)) {
        dprintf(conn, "OK %ld CACHED\n", now_ms() - t0);
        _exit(0);
    }
    char *argv[4];
    argv[0] = (char *)"siluc";
    argv[1] = src;
    argv[2] = (char *)"-o";
    argv[3] = out;
    if (g_dbg_fd >= 0) dprintf(g_dbg_fd, "silucd: child starting compile\n");
    int crc = run_compile(4, argv);
    if (g_dbg_fd >= 0) dprintf(g_dbg_fd, "silucd: child compile rc=%d\n", crc);
    /* the captured diagnostics stream before the verdict on BOTH
       paths - a failed link's ld details reach the client (review S6) */
    char diag[8192];
    lseek(err_fd, 0, SEEK_SET);
    ssize_t dn;
    while ((dn = read(err_fd, diag, sizeof diag)) > 0) {
        if (write(conn, diag, (size_t)dn) < 0) break;
    }
    if (crc != 0) {
        dprintf(conn, "ERR compile failed\n");
        _exit(1);
    }
    build_cache_record(hash, out);
    dprintf(conn, "OK %ld built\n", now_ms() - t0);
    _exit(0);
}

static int g_server_fd = -1;
static char g_sock_path[4096];

static void serve_teardown(void) {
    if (g_serving_child) return; /* a die()ing child must not unlink */
    if (g_server_fd >= 0) close(g_server_fd);
    unlink(g_sock_path);
}

static int serve_mode(void) {
    compute_cache_dir();
    make_cache_dirs(g_cache_dir);
    snprintf(g_sock_path, sizeof g_sock_path, "%s/silucd.sock", g_cache_dir);

    signal(SIGPIPE, SIG_IGN);
    signal(SIGCHLD, SIG_IGN); /* no zombies */

    /* stale socket from a dead daemon: a refused connect means it is
       safe to take over; a live daemon means we are done (idempotent) */
    struct sockaddr_un addr;
    memset(&addr, 0, sizeof addr);
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, g_sock_path, sizeof addr.sun_path - 1);
    int probe = socket(AF_UNIX, SOCK_STREAM, 0);
    if (probe >= 0) {
        int alive = (connect(probe, (struct sockaddr *)&addr, sizeof addr) == 0);
        close(probe);
        if (alive) return 0;
        unlink(g_sock_path);
    }

    g_dbg_fd = dup(2);
    g_server_fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (g_server_fd < 0) die("daemon socket");
    if (bind(g_server_fd, (struct sockaddr *)&addr, sizeof addr) != 0)
        die("daemon bind (socket in use?)");
    if (listen(g_server_fd, 16) != 0) die("daemon listen");
    atexit(serve_teardown);
    fprintf(stderr, "silucd: listening on %s\n", g_sock_path);

    for (;;) {
        fd_set rfds;
        FD_ZERO(&rfds);
        FD_SET(g_server_fd, &rfds);
        struct timeval tv = { 300, 0 }; /* idle exit: no requests in 5min */
        int r = select(g_server_fd + 1, &rfds, NULL, NULL, &tv);
        if (r <= 0) {
            serve_teardown();
            _exit(0);
        }
        int conn = accept(g_server_fd, NULL, NULL);
        if (conn < 0) continue;
        pid_t pid = fork();
        if (pid == 0) {
            close(g_server_fd);
            serve_request(conn);
        }
        close(conn); /* parent: the child owns the connection */
    }
}

/* self path for the daemon exec */
static char g_self_buf[4096];
static const char *resolve_self(void) {
    ssize_t n = readlink("/proc/self/exe", g_self_buf, sizeof g_self_buf - 1);
#ifdef __APPLE__
    if (n < 0) {
        uint32_t sz = sizeof g_self_buf;
        if (_NSGetExecutablePath(g_self_buf, &sz) == 0)
            n = strlen(g_self_buf);
    }
#endif
    if (n < 0 || (size_t)n >= sizeof g_self_buf) return "siluc";
    g_self_buf[n] = 0;
    return g_self_buf;
}

/* client forward: returns 0 when the daemon handled the build, 1 when
   the daemon REPORTED a compile error, -1 to fall through to the
   direct path (no daemon reachable) */
static int try_forward(const char *src_abs, const char *out) {
    snprintf(g_sock_path, sizeof g_sock_path, "%s/silucd.sock", g_cache_dir);
    struct sockaddr_un addr;
    memset(&addr, 0, sizeof addr);
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, g_sock_path, sizeof addr.sun_path - 1);
    signal(SIGPIPE, SIG_IGN);

    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    if (connect(fd, (struct sockaddr *)&addr, sizeof addr) != 0) {
        if (getenv("SILUC_DEBUG")) fprintf(stderr, "silucd: connect refused (%s), auto-start\n", strerror(errno));
        close(fd);
        /* auto-start: spawn a detached daemon, then retry briefly */
        const char *da = getenv("SILUC_DAEMON");
        if (!da || strcmp(da, "0") == 0) return -1;
        const char *self_exe = resolve_self();
        pid_t pid = fork();
        if (pid == 0) {
            setsid();
            /* detach ALL stdio: inherited stdout/stderr kept the
               starting client's pipe open - a caller waiting for EOF
               hung until the daemon's 300s idle exit (review S3) */
            int dn = open("/dev/null", O_RDWR);
            if (dn >= 0) {
                dup2(dn, 0);
                dup2(dn, 1);
                dup2(dn, 2);
                if (dn > 2) close(dn);
            }
            execl(self_exe, "siluc", "--serve", (char *)NULL);
            _exit(1);
        }
        int started = 0;
        for (int i = 0; i < 40 && !started; i++) {
            usleep(50000); /* 2s worst case */
            fd = socket(AF_UNIX, SOCK_STREAM, 0);
            if (fd < 0) return -1;
            if (connect(fd, (struct sockaddr *)&addr, sizeof addr) == 0)
                started = 1;
            else
                close(fd);
        }
        if (!started) return -1;
    }
    struct timeval tv = { 600, 0 };
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    char req[8192];
    snprintf(req, sizeof req, "COMPILE %s %s\n", src_abs, out);
    if (getenv("SILUC_DEBUG")) fprintf(stderr, "silucd: client sending req\n");
    if (write(fd, req, strlen(req)) < 0) {
        if (getenv("SILUC_DEBUG")) fprintf(stderr, "silucd: client write failed: %s\n", strerror(errno));
        close(fd); return -1;
    }
    /* read to EOF into a growing buffer: the verdict is the LAST line
       and diagnostics can exceed any fixed size (review S4) */
    size_t cap = 65536;
    char *resp = (char *)malloc(cap);
    if (!resp) { close(fd); return -1; }
    size_t got = 0;
    ssize_t n;
    for (;;) {
        if (got == cap) {
            if (cap >= (8u << 20)) break; /* absurd diagnostics: stop */
            cap *= 2;
            char *bigger = (char *)realloc(resp, cap);
            if (!bigger) break;
            resp = bigger;
        }
        n = read(fd, resp + got, cap - got);
        if (n <= 0) break;
        got += (size_t)n;
    }
    close(fd);
    if (getenv("SILUC_DEBUG")) fprintf(stderr, "silucd: client got %zu bytes\n", got);
    if (got == 0) { free(resp); return -1; }
    resp[got] = 0;
    resp[got] = 0;
    /* EOF-delimited protocol: everything on the connection is the
       build's diagnostics (the child wires its stderr here); the FINAL
       line is the OK/ERR verdict. Diagnostics stream to our stderr. */
    char *verdict = NULL;
    char *cur = resp;
    while (cur && *cur) {
        char *eol = strchr(cur, '\n');
        if (!eol) break;
        *eol = 0;
        if (strncmp(cur, "OK ", 3) == 0 || strncmp(cur, "ERR", 3) == 0)
            verdict = cur;
        else if (cur[0])
            fprintf(stderr, "silucd: %s\n", cur);
        cur = eol + 1;
    }
    if (verdict && strncmp(verdict, "OK", 2) == 0) {
        printf("silucd: %s\n", verdict);
        return 0;
    }
    if (verdict)
        fprintf(stderr, "silucd: %s\n", verdict);
    return 1;
}

int main(int argc, char **argv) {
    const char *src = NULL, *out = NULL;
    int want_serve = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-o") == 0 && i + 1 < argc) out = argv[++i];
        else if (strcmp(argv[i], "--object") == 0) g_object_mode = 1;
        else if (strcmp(argv[i], "--no-lto") == 0) g_no_lto = 1;
        else if (strcmp(argv[i], "--serve") == 0) want_serve = 1;
        else if (argv[i][0] != '-') src = argv[i];
    }
    if (want_serve) return serve_mode();

    compute_cache_dir();
    if (src && out && g_object_mode == 0 && g_no_lto == 0
            && getenv("SILUC_DAEMON")) {
        /* resolve src AND out against the cwd exactly like
           run_compile does - a relative out used to land in the
           daemon's cwd and record relative cache keys (review S2) */
        char src_abs[4096], out_abs[4096];
        if (src[0] == '/') snprintf(src_abs, sizeof src_abs, "%s", src);
        else {
            if (!getcwd(src_abs, sizeof src_abs)) die("getcwd");
            strncat(src_abs, "/", sizeof src_abs - strlen(src_abs) - 1);
            strncat(src_abs, src, sizeof src_abs - strlen(src_abs) - 1);
        }
        if (out[0] == '/') snprintf(out_abs, sizeof out_abs, "%s", out);
        else {
            if (!getcwd(out_abs, sizeof out_abs)) die("getcwd");
            strncat(out_abs, "/", sizeof out_abs - strlen(out_abs) - 1);
            strncat(out_abs, out, sizeof out_abs - strlen(out_abs) - 1);
        }
        /* the line protocol is space-tokenized: paths with whitespace
           go direct (review S5) */
        if (strchr(src_abs, ' ') || strchr(out_abs, ' ')
                || strchr(src_abs, '\n') || strchr(out_abs, '\n')) {
            make_cache_dirs(g_cache_dir);
            return run_compile(argc, argv);
        }
        /* only the default link mode forwards; flags stay direct */
        int fw = try_forward(src_abs, out_abs);
        if (getenv("SILUC_DEBUG")) fprintf(stderr, "silucd: try_forward -> %d\n", fw);
        if (fw >= 0) return fw;
        /* fall through: direct compile, untouched path */
        make_cache_dirs(g_cache_dir);
        return run_compile(argc, argv);
    }
    make_cache_dirs(g_cache_dir);
    return run_compile(argc, argv);
}
