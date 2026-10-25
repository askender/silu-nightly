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
 * runtime object. No Python anywhere.
 *
 * Cache layout (~/.cache/silu-runtime/driver/):
 *   rt.ll    - the runtime prefix text (the converter emits it as a
 *              strict prefix of every program; rebuilt when missing)
 *   rt.syms  - "kind\\tret-or-type\\tname" lines for every runtime
 *              symbol (for declaration synthesis)
 *   rt.o     - the compiled runtime object
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <libgen.h>
#include <mach-o/dyld.h>
#include <fcntl.h>

#define MAX_LL (64 * 1024 * 1024)
#define MAX_SYMS 4096
#define LINE 8192

static char g_exe_dir[4096];
static char g_cache_dir[4096];

static void die(const char *msg) {
    fprintf(stderr, "siluc: %s\n", msg);
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

static int run_quiet(const char *argv[]) {
    pid_t pid = fork();
    if (pid < 0) die("fork");
    if (pid == 0) {
        int devnull = open("/dev/null", 1 /*O_WRONLY*/);
        dup2(devnull, 1);
        dup2(devnull, 2);
        execvp(argv[0], (char *const *)argv);
        _exit(127);
    }
    int status;
    waitpid(pid, &status, 0);
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}

/* ---------- runtime prefix split + declaration synthesis ---------- */

typedef struct {
    char kind;            /* 'f' function, 'g' global */
    char sig[LINE];       /* full define-line text or global type */
    char name[256];
} Sym;

static Sym g_syms[MAX_SYMS];
static int g_nsyms = 0;

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
            /* @"name" = [internal] global <type> ... */
            const char *eq = strstr(p, "= ");
            if (eq && eq < eol) {
                const char *gp = strstr(eq, "global ");
                if (gp && gp < eol) {
                    Sym *s = &g_syms[g_nsyms++];
                    s->kind = 'g';
                    const char *nm = p + 2;
                    const char *close = strchr(nm, '"');
                    size_t nmlen = close - nm;
                    if (nmlen > 255) nmlen = 255;
                    memcpy(s->name, nm, nmlen);
                    s->name[nmlen] = 0;
                    /* type text after 'global ' up to comma/newline */
                    const char *t = gp + 7;
                    const char *tend = eol;
                    const char *comma = strchr(t, ',');
                    if (comma && comma < tend) tend = comma;
                    /* scalar types end at the first space (the
                       initializer follows); bracketed types run to
                       the matching close */
                    if (*t != '[' && *t != '{') {
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
static int user_defines(const char *body, const char *name, size_t len) {
    const char *p = body;
    while ((p = strstr(p, "@\"")) != NULL) {
        if (strncmp(p + 2, name, len) == 0 && p[2 + len] == '"') {
            /* check it is a definition: preceded by define at line
               start, or '=' for globals */
            const char *bol = p;
            while (bol > body && bol[-1] != '\n') bol--;
            size_t plen = p - bol;
            if ((plen >= 7 && strncmp(bol, "define ", 7) == 0))
                return 1;
            const char *after = p + 2 + len + 1;
            while (*after == ' ') after++;
            if (*after == '=') return 1;
        }
        p += 2;
    }
    return 0;
}

static int g_object_mode = 0;

/* map an LLVM type token to the C type for the header */
static const char *c_type_of(const char *ll_ty) {
    if (strcmp(ll_ty, "i64") == 0) return "int64_t";
    if (strcmp(ll_ty, "double") == 0) return "double";
    if (strcmp(ll_ty, "i1") == 0) return "bool";
    if (strcmp(ll_ty, "i8*") == 0) return "const char*";
    return "void*"; /* pyobj and raw structs pass as opaque */
}

int main(int argc, char **argv) {
    const char *src = NULL, *out = NULL;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-o") == 0 && i + 1 < argc) out = argv[++i];
        else if (strcmp(argv[i], "--object") == 0) g_object_mode = 1;
        else if (argv[i][0] != '-') src = argv[i];
    }
    if (!src || !out) {
        fprintf(stderr, "usage: siluc file.si -o output [--object]\n");
        return 2;
    }

    /* locate siluc1 next to this driver */
    ssize_t n = readlink("/proc/self/exe", g_exe_dir, sizeof g_exe_dir);
    if (n < 0) {
        /* macOS */
        char tmp[4096];
        uint32_t sz = sizeof tmp;
        if (_NSGetExecutablePath(tmp, &sz) == 0) {
            strcpy(g_exe_dir, tmp);
            n = strlen(g_exe_dir);
        }
    }
    if (n < 0 || (size_t)n >= sizeof g_exe_dir) die("locating self");
    g_exe_dir[n] = 0;
    char *dir = dirname(g_exe_dir);
    char siluc1[4096];
    snprintf(siluc1, sizeof siluc1, "%s/siluc1", dir);

    /* cache dir */
    const char *home = getenv("HOME");
    snprintf(g_cache_dir, sizeof g_cache_dir, "%s/.cache/silu-runtime/driver", home ? home : ".");
    mkdir(g_cache_dir, 0755);

    char rt_ll_path[4096], rt_o_path[4096], rt_syms_path[4096];
    snprintf(rt_ll_path, sizeof rt_ll_path, "%s/rt.ll", g_cache_dir);
    snprintf(rt_o_path, sizeof rt_o_path, "%s/rt.o", g_cache_dir);
    snprintf(rt_syms_path, sizeof rt_syms_path, "%s/rt.syms", g_cache_dir);

    struct stat st;
    int have_rt = stat(rt_ll_path, &st) == 0 && stat(rt_o_path, &st) == 0;

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
        const char *c1[] = { "clang", "-O2", "-c", lifted_path, "-o", rt_o_path, NULL };
        if (run_quiet(c1) != 0) die("clang failed on the runtime");
    }

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
            if (s && !user_defines(body, nm, len)) {
                char one[LINE + 300];
                if (s->kind == 'f') {
                    /* declare <ret> @"name"(...) - the return type is
                       the text between 'define ' and ' @"' */
                    const char *ret = s->sig + 7;
                    const char *at = strstr(s->sig, " @\"");
                    if (at && at > ret) {
                        size_t rl = at - ret;
                        char rbuf[LINE];
                        if (rl > LINE - 1) rl = LINE - 1;
                        memcpy(rbuf, ret, rl);
                        rbuf[rl] = 0;
                        snprintf(one, sizeof one, "declare %s @\"%s\"(...)\n",
                                 rbuf, s->name);
                    } else {
                        continue;
                    }
                } else {
                    snprintf(one, sizeof one, "@\"%s\" = external global %s\n",
                             s->name, s->sig);
                }
                if (!strstr(decls, one))
                    strcat(decls, one);
            }
            p = close;
        }
    }

    /* 6. user .ll = fixed header + header declares + synth decls + body */
    char user_ll_path[] = "/tmp/siluc_userXXXXXX.ll";
    int ufd = mkstemps(user_ll_path, 3);
    FILE *uf = ufd >= 0 ? fdopen(ufd, "w") : NULL;
    if (!uf) die("cannot create user .ll");
    fputs("; ModuleID = \"silu_user\"\n"
          "target triple = \"arm64-apple-darwin24.6.0\"\n"
          "target datalayout = \"e-m:o-p270:32:32-p271:32:32-p272:64:64-"
          "i64:64-i128:128-n32:64-S128-Fn32\"\n\n", uf);
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
        const char *co[] = { "clang", "-O2", "-c", obj_ll, "-o", out, NULL };
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

    /* 7. clang user + link */
    char user_o_path[] = "/tmp/siluc_userXXXXXX.o";
    int ofd = mkstemps(user_o_path, 2);
    close(ofd);
    const char *c2[] = { "clang", "-O2", "-c", user_ll_path, "-o", user_o_path, NULL };
    if (run_quiet(c2) != 0) die("clang failed on the user module");
    const char *c3[] = { "clang", user_o_path, rt_o_path, "-o", out, "-Wl,-dead_strip", NULL };
    if (run_quiet(c3) != 0) die("link failed");

    /* unlink(user_ll_path); unlink(user_o_path); */
    return 0;
}
