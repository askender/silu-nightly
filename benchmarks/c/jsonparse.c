#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct J J;
struct J { int tag; long i; char *s; J **arr; int alen; struct { char **k; J **v; int n; } obj; };
static char *S; static long P;
static char *pstr(long lo, long hi) { char *b = malloc(hi - lo + 1); memcpy(b, S + lo, hi - lo); b[hi - lo] = 0; return b; }
static J *newj(int t) { J *j = calloc(1, sizeof(J)); j->tag = t; return j; }
static J *pv(void);
static J *parr(void) { J *j = newj(5); int cap = 8; j->arr = malloc(cap * sizeof(J*)); P++;
    while (S[P] != ']') { if (j->alen == cap) { cap *= 2; j->arr = realloc(j->arr, cap * sizeof(J*)); } j->arr[j->alen++] = pv(); if (S[P] == ',') P++; }
    P++; return j; }
static J *pobj(void) { J *j = newj(6); int cap = 8; j->obj.k = malloc(cap * sizeof(char*)); j->obj.v = malloc(cap * sizeof(J*)); P++;
    while (S[P] != '}') { P++; long st = P; while (S[P] != '"') P++; char *k = pstr(st, P); P += 2;
        if (j->obj.n == cap) { cap *= 2; j->obj.k = realloc(j->obj.k, cap * sizeof(char*)); j->obj.v = realloc(j->obj.v, cap * sizeof(J*)); }
        j->obj.k[j->obj.n] = k; j->obj.v[j->obj.n] = pv(); j->obj.n++; if (S[P] == ',') P++; }
    P++; return j; }
static J *pv(void) { char c = S[P];
    if (c == '{') return pobj();
    if (c == '[') return parr();
    if (c == '"') { P++; long st = P; while (S[P] != '"') P++; J *j = newj(4); j->s = pstr(st, P); P++; return j; }
    long n = 0; while (S[P] >= '0' && S[P] <= '9') n = n * 10 + (S[P++] - '0'); J *j = newj(1); j->i = n; return j; }
int main(void) { fseek(stdin, 0, SEEK_END); long n = ftell(stdin); rewind(stdin);
    S = malloc(n + 1); fread(S, 1, n, stdin); S[n] = 0;
    J *d = pv();
    long total = 0, count = 0, csum = 0, nn = 0;
    if (d->tag == 5) { count = d->alen;
        for (int i = 0; i < d->alen; i++) { J *o = d->arr[i];
            if (o->tag == 6) { for (int f = 0; f < o->obj.n; f++) {
                if (!strcmp(o->obj.k[f], "id") && o->obj.v[f]->tag == 1) total += o->obj.v[f]->i;
                if (!strcmp(o->obj.k[f], "name") && o->obj.v[f]->tag == 4) { csum += strlen(o->obj.v[f]->s); nn++; } } } } }
    printf("%ld %ld %ld %ld\n", total, count, csum, nn); return 0; }
