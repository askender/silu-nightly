// shim_dec_bits.c - exact decimal->binary64 for the WAT assembler:
// correctly-rounded (nearest-even) conversion of D * 10^e where D is a
// u64 digit accumulator (shortest-repr inputs have <= 17 significant
// digits) and e any int32 decimal exponent. 128-bit fixed point in
// 4 x 32-bit digits - no libc, no 128-bit type, wasm64-native. Pure C
// so it can be unit-tested natively against CPython-generated vectors.
//
// Rounding discipline: bits dropped from the register's bottom
// accumulate as guard (the first dropped MSB) + sticky (everything
// else below it); the final cut keeps the top 53 bits and rounds by
// guard && (sticky || odd).  For large positive e a 4-bit pre-shift
// makes room so the register's top never overflows the 128 bits.
#include <stdint.h>

static void mul10(uint32_t d[4]) {
    uint64_t carry = 0;
    for (int i = 0; i < 4; i++) {
        uint64_t cur = (uint64_t)d[i] * 10ULL + carry;
        d[i] = (uint32_t)(cur & 0xFFFFFFFFu);
        carry = cur >> 32;
    }
}

static int div5(uint32_t d[4]) {
    uint64_t rem = 0;
    for (int i = 3; i >= 0; i--) {
        uint64_t cur = (rem << 32) | d[i];
        d[i] = (uint32_t)(cur / 5ULL);
        rem = cur % 5ULL;
    }
    return (int)rem;
}

static int shiftr4(uint32_t d[4]) {
    int dropped = (int)(d[0] & 0xFu);
    for (int i = 0; i < 3; i++) {
        d[i] = (d[i] >> 4) | ((d[i + 1] & 0xFu) << 28);
    }
    d[3] >>= 4;
    return dropped;
}

static void shiftl1(uint32_t d[4]) {
    for (int i = 3; i > 0; i--) {
        d[i] = (d[i] << 1) | (d[i - 1] >> 31);
    }
    d[0] <<= 1;
}

static void shiftl(uint32_t d[4], int s) {
    for (int i = 0; i < s; i++) shiftl1(d);
}

static int topbit128(const uint32_t d[4]) {
    for (int i = 3; i >= 0; i--) {
        if (d[i]) {
            int b = 31;
            while (((d[i] >> b) & 1u) == 0) b--;
            return i * 32 + b + 1;
        }
    }
    return 0;
}

uint64_t shim_dec_bits(int64_t D, int64_t e, int64_t neg) {
    if (D == 0) return neg ? 0x8000000000000000ULL : 0ULL;
    uint32_t d[4] = { (uint32_t)D, (uint32_t)(D >> 32), 0u, 0u };
    int pguard = 0, psticky = 0, have_p = 0;
    int bexp = 0;
    if (e >= 0) {
        // *10^e: the register takes the full *10 (bexp unchanged);
        // pre-drop the bottom 4 bits when the top nears overflow
        // (dropped bits feed guard/sticky, *2^4 -> bexp += 4)
        for (int i = 0; i < e; i++) {
            int mb = topbit128(d);
            if (mb > 96) {
                int dr = shiftr4(d);
                int msb = (dr >> 3) & 1;
                if (!have_p) { pguard = msb; have_p = 1; }
                if (dr & 0x7) psticky = 1;
                if (dr) psticky = 1;
                bexp += 4;
            }
            mul10(d);
        }
    } else {
        int mb0 = topbit128(d);
        int lz = 128 - mb0;
        shiftl(d, lz);
        bexp -= lz;
        // /10^k = /5^k /2^k: the register takes /5 (bexp -= 1 per
        // /5), the refill shiftl takes the /2 parts
        int k = -e;
        while (k > 0) {
            int rem = div5(d);
            // the /2 half of /10 always moves the exponent; the /5
            // remainder feeds guard/sticky
            bexp -= 1;
            if (rem) {
                int msb = rem >= 3;
                if (!have_p) { pguard = msb; have_p = 1; }
                if (rem & 0x3) psticky = 1;
                if (rem) psticky = 1;
            }
            k -= 1;
            int mb = topbit128(d);
            if (mb > 0 && mb < 97) {
                int s = 97 - mb;
                shiftl(d, s);
                bexp -= s;
            }
        }
    }
    int mb = topbit128(d);
    int shift = mb - 53;
    uint64_t mant;
    if (shift <= 0) {
        // exact: shift up so the leading bit lands at position 52
        shiftl(d, -shift);
        mant = ((uint64_t)d[1] << 32) | d[0];
        bexp += shift;
    } else {
        int gp = shift - 1;
        int guard2 = (d[gp >> 5] >> (gp & 31)) & 1;
        int low2 = pguard | psticky;
        for (int i = 0; i < 4 && !low2; i++) {
            int base = i * 32;
            uint32_t mask;
            if (base + 32 <= gp) mask = 0xFFFFFFFFu;
            else if (base >= gp) mask = 0u;
            else mask = (uint32_t)((1u << (gp - base)) - 1u);
            if (d[i] & mask) low2 = 1;
        }
        if (shift >= 64) {
            uint64_t hi = ((uint64_t)d[3] << 32) | d[2];
            int s2 = shift - 64;
            mant = s2 ? (hi >> s2) : hi;
        } else {
            uint64_t hi = ((uint64_t)d[3] << 32) | d[2];
            uint64_t lo = ((uint64_t)d[1] << 32) | d[0];
            mant = (lo >> shift) | (hi << (64 - shift));
        }
        if (guard2 && (low2 || (mant & 1ULL))) mant += 1;
        if (mant >> 53) { mant >>= 1; bexp += 1; }
        bexp += shift;
    }
    int se = bexp + 1075;    // value = mant * 2^(bexp), mant 53 bits
    if (mant == 0) return neg ? 0x8000000000000000ULL : 0ULL;
    if (se >= 2047) {
        uint64_t inf = 0x7FF0000000000000ULL;
        return neg ? (inf | 0x8000000000000000ULL) : inf;
    }
    if (se <= 0) {
        int sh = 1 - se;     // subnormal: extra right shift with round
        int g2 = (sh >= 1 && sh <= 64) ? (int)((mant >> (sh - 1)) & 1ULL) : 0;
        int st2 = (sh > 64) ? (mant != 0)
                            : ((mant & ((1ULL << (sh - 1)) - 1ULL)) != 0);
        mant >>= sh;
        if (g2 && (st2 || (mant & 1ULL))) mant += 1;
        se = 0;
    }
    uint64_t out = ((uint64_t)(uint32_t)se << 52) | (mant & 0x000FFFFFFFFFFFFFULL);
    if (neg) out |= 0x8000000000000000ULL;
    return out;
}
