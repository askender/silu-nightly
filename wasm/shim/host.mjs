// host.mjs - JS host for freestanding wasm64 Silu compiler modules.
//
// Satisfies the silu_host import surface declared in shim_libc.c:
//   mem_grow, die, write, fmt_double, strtod, getchar, pow,
//   file_open/file_read/file_seek/file_tell/file_close, exit
// All wasm64 i64 boundary values arrive as BigInt; pointers are BigInt.
//
// CLI: node host.mjs <module.wasm> [input-file] [--file NAME=PATH]...
// stdin of the guest = input-file bytes (or --stdin-data); guest stdout
// goes to this process's stdout, exit code propagates.

const latin1Dec = new TextDecoder("latin1");
const latin1 = (bytes) => latin1Dec.decode(bytes);

function concatU8(chunks) {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const out = new Uint8Array(total);
  let at = 0;
  for (const c of chunks) out.set(c, at), (at += c.length);
  return out;
}

/* ---------- C-like double formatting (%f / %e / %g) ----------
 * Byte-compatibility target: the platform C library (verified by
 * wasm/test_shim.mjs against wasm/test_shim_ref.c output).
 * - %f: exact BigInt expansion of the double (toFixed falls back to
 *   exponential notation at >=1e21 and would break byte identity)
 * - rounding: half-even on the exact decimal expansion (IEEE default)
 * - %g: trailing-zero stripping touches the mantissa only */

const f64bits = new DataView(new ArrayBuffer(8));

function decompose(v) {
  f64bits.setFloat64(0, v);
  const bits = f64bits.getBigUint64(0);
  const neg = bits >> 63n === 1n;
  const expF = Number((bits >> 52n) & 0x7ffn);
  const frac = bits & ((1n << 52n) - 1n);
  return { neg, expF, frac, M: expF === 0 ? frac : frac | (1n << 52n), E: expF === 0 ? -1074 : expF - 1075 };
}

// exact |v| rendered with exactly `prec` digits after the point
function fixedExact(v, prec) {
  const { M, E } = decompose(v);
  let digits; // |v| * 10^prec, rounded half-even
  if (E >= 0) {
    digits = (M << BigInt(E)) * 10n ** BigInt(prec);
  } else if (prec + E >= 0) {
    digits = M * 5n ** BigInt(prec) << BigInt(E + prec);
  } else {
    const num = M * 5n ** BigInt(prec);
    const den = 1n << BigInt(-(E + prec));
    const q = num / den;
    const r2 = (num % den) * 2n;
    digits = r2 > den || (r2 === den && (q & 1n) === 1n) ? q + 1n : q;
  }
  let s = digits.toString();
  if (prec > 0) {
    s = s.padStart(prec + 1, "0");
    s = s.slice(0, -prec) + "." + s.slice(-prec);
  }
  return s;
}

function fixExp(s, upper) {
  // JS "1.5e+0" -> C "1.500000e+00" (exponent >= 2 digits)
  let [m, e] = s.split("e");
  const xi = parseInt(e, 10);
  const sign = xi < 0 ? "-" : "+";
  e = (upper ? "E" : "e") + sign + String(Math.abs(xi)).padStart(2, "0");
  return m + e;
}

function cFormatDouble(v, spec, prec) {
  if (prec < 0) prec = 6;
  const { neg, expF, frac } = decompose(v);
  const sign = neg ? "-" : "";
  if (expF === 0x7ff) return sign + (frac === 0n ? "inf" : "nan");
  const abs = Math.abs(v);
  if (spec === "f") return sign + fixedExact(abs, prec);
  if (spec === "e" || spec === "E") return sign + fixExp(abs.toExponential(prec), spec === "E");
  // %g / %G
  const P = prec === 0 ? 1 : prec;
  if (abs === 0) return sign + "0";
  const xs = abs.toExponential(P - 1);
  const X = parseInt(xs.split("e")[1], 10);
  if (X >= -4 && X < P) {
    return sign + fixExpTail(fixedExact(abs, Math.max(P - 1 - X, 0)));
  }
  const s = fixExp(xs, spec === "G");
  const ei = s.search(/e[+-]/);
  return sign + s.slice(0, ei).replace(/0+$/, "").replace(/\.$/, "") + s.slice(ei);
}

function fixExpTail(s) {
  // strip trailing zeros in the fraction of a plain fixed string
  if (!s.includes(".")) return s;
  return s.replace(/0+$/, "").replace(/\.$/, "");
}


const hexpow = new DataView(new ArrayBuffer(8));
function hexFloat(neg, hexStr, fracLen, pexp) {
  // value = hexStr * 2^(pexp - 4*fracLen), correctly rounded half-even
  let v = BigInt("0x" + (hexStr || "0"));
  let e2 = pexp - 4 * fracLen;
  if (v === 0n) return neg ? -0 : 0;
  let bl = v.toString(2).length;
  if (bl > 53) {
    const shift = BigInt(bl - 53);
    const lost = v & ((1n << shift) - 1n);
    const half = 1n << (shift - 1n);
    v >>= shift;
    e2 += Number(shift);
    if (lost > half || (lost === half && (v & 1n) === 1n)) v += 1n;
    if (v >> 53n !== 0n) { v >>= 1n; e2++; }
    bl = 53;
  }
  // normalize: value = v * 2^e2 with v < 2^53
  let exp = e2 + bl - 1; // unbiased exponent
  let mant = v;
  if (exp > 1023) return neg ? -Infinity : Infinity;
  if (exp < -1074) return neg ? -0 : 0;
  if (exp < -1021) {
    // subnormal: shift mantissa so exponent field is 0
    const sh = -1021 - exp;
    mant = mant >> BigInt(sh - 1);
    const lost = mant & 1n;
    mant >>= 1n;
    if (lost === 1n) mant += 1n; // approx half-even; denormal hex literals never occur in Silu source
    exp = -1022;
    if (mant >> 52n === 1n) { mant >>= 1n; exp = -1021; }
  } else {
    mant -= 1n << BigInt(bl - 1); // remove the implicit leading bit
  }
  const bits = (BigInt(neg ? 1 : 0) << 63n) | BigInt(exp + 1023) << 52n | mant;
  hexpow.setBigUint64(0, bits);
  return hexpow.getFloat64(0);
}

function cStrtod(bytes, offset, len) {
  let i = offset;
  const end = offset + len;
  const isWs = (c) => c === 32 || (c >= 9 && c <= 13);
  while (i < end && isWs(bytes[i])) i++;
  let j = i;
  if (j < end && (bytes[j] === 43 || bytes[j] === 45)) j++;
  const wordStart = j;
  // infinity / nan words
  const lowerFrom = (k, n) => {
    if (k + n > end) return false;
    for (let t = 0; t < n; t++) {
      const c = bytes[k + t];
      if ((c | 32) !== "infinity"[t].charCodeAt(0) % 128) return false;
    }
    return true;
  };
  if (lowerFrom(j, 8) && latin1(bytes.subarray(j, j + 8)).toLowerCase() === "infinity") {
    const val = bytes[j] === 45 ? -Infinity : Infinity;
    return { value: val, consumed: j + 8 - offset };
  }
  if (j + 3 <= end && latin1(bytes.subarray(j, j + 3)).toLowerCase() === "inf") {
    const val = bytes[j] === 45 ? -Infinity : Infinity;
    return { value: val, consumed: j + 3 - offset };
  }
  if (j + 3 <= end && latin1(bytes.subarray(j, j + 3)).toLowerCase() === "nan") {
    return { value: NaN, consumed: j + 3 - offset };
  }
  // hex float: 0x hexdigits [ . hexdigits ] [ pP [sign] decimals ]
  if (j + 2 < end && bytes[j] === 48 && (bytes[j + 1] === 120 || bytes[j + 1] === 88)) {
    const isH = (c) => (c >= 48 && c <= 57) || (c >= 97 && c <= 102) || (c >= 65 && c <= 70);
    let k = j + 2;
    let hd = 0;
    while (k < end && isH(bytes[k])) k++, hd++;
    let fl = 0;
    if (k < end && bytes[k] === 46) {
      k++;
      while (k < end && isH(bytes[k])) k++, hd++, fl++;
    }
    if (hd > 0) {
      let last = k;
      let pexp = 0;
      if (k < end && (bytes[k] === 112 || bytes[k] === 80)) {
        let e = k + 1;
        if (e < end && (bytes[e] === 43 || bytes[e] === 45)) e++;
        let ed = 0;
        while (e < end && bytes[e] >= 48 && bytes[e] <= 57) e++, ed++;
        if (ed > 0) {
          pexp = parseInt(latin1(bytes.subarray(k + 1, e)), 10);
          if (bytes[k + 1] === 45) pexp = -pexp;
          last = e;
        }
      }
      const hexStr = latin1(bytes.subarray(j + 2, k)).replace(".", "");
      const value = hexFloat(bytes[j] === 45, hexStr, fl, pexp);
      return { value, consumed: last - offset };
    }
    // "0x" without hex digits: C consumes just the leading "0"
  }
  // decimal: digits [. digits] [ (e|E) [sign] digits ]
  let k = j;
  let digits = 0;
  while (k < end && bytes[k] >= 48 && bytes[k] <= 57) k++, digits++;
  if (k < end && bytes[k] === 46) {
    k++;
    while (k < end && bytes[k] >= 48 && bytes[k] <= 57) k++, digits++;
  }
  if (digits === 0) return { value: 0, consumed: 0 };
  let last = k;
  if (k < end && (bytes[k] === 101 || bytes[k] === 69)) {
    let e = k + 1;
    if (e < end && (bytes[e] === 43 || bytes[e] === 45)) e++;
    let ed = 0;
    while (e < end && bytes[e] >= 48 && bytes[e] <= 57) e++, ed++;
    if (ed > 0) last = e;
  }
  const text = latin1(bytes.subarray(i, last));
  const value = parseFloat(text);
  return { value, consumed: last - offset };
}

/* ---------- host ---------- */

export async function runWasm({ wasmPath, wasmBytes, stdin = new Uint8Array(), files = new Map() }) {
  const { instantiate } = await makeHost(files, stdin);
  const bytes = wasmBytes ?? new Uint8Array((await import("node:fs")).readFileSync(wasmPath));
  const { module } = await instantiate(bytes);
  return module; // {exports, done: Promise<{exitCode, stdout, stderr}>}
}

function makeHost(files, stdinBytes) {
  let memory = null;
  let stdout = [];
  let stderr = [];
  let exitCode = null;
  let exitResolve;
  const exited = new Promise((r) => (exitResolve = r));

  const dec = (ptr, len) =>
    latin1Dec.decode(new Uint8Array(memory.buffer, Number(ptr), Number(len)));
  const out = (fd, ptr, len) => {
    const chunk = new Uint8Array(memory.buffer, Number(ptr), Number(len)).slice();
    (fd === 2 ? stderr : stdout).push(chunk);
  };

  // stdin cursor
  let stdinPos = 0;
  // file table: id -> {bytes, pos}
  const openFiles = new Map();
  let nextFileId = 1;

  const imports = {
    silu_host: {
      mem_grow(pagesBig) {
        const old = memory.grow(Number(pagesBig));
        return old === -1 ? -1n : BigInt(old);
      },
      die(ptr, len) {
        const msg = dec(ptr, len);
        stderr.push(new TextEncoder().encode(`shim die: ${msg}\n`));
        exitCode = 70;
        exitResolve();
        throw new SiluExit(70);
      },
      write(fd, ptr, len) {
        out(Number(fd), ptr, len);
      },
      fmt_double(buf, cap, v, spec, prec) {
        const s = cFormatDouble(Number(v), String.fromCharCode(Number(spec)), Number(prec));
        const bytes = new TextEncoder().encode(s); // ascii-only by construction
        if (bytes.length >= Number(cap)) return -1n;
        new Uint8Array(memory.buffer, Number(buf), bytes.length).set(bytes);
        return BigInt(bytes.length);
      },
      strtod(ptr, len, consumedPtr) {
        const bytes = new Uint8Array(memory.buffer, Number(ptr), Number(len)).slice();
        const { value, consumed } = cStrtod(bytes, 0, Number(len));
        new DataView(memory.buffer).setBigUint64(Number(consumedPtr), BigInt(consumed), true);
        return value;
      },
      getchar() {
        return stdinPos < stdinBytes.length ? stdinBytes[stdinPos++] : -1;
      },
      pow(a, b) {
        return Math.pow(Number(a), Number(b));
      },
      file_open(ptr, len) {
        const name = dec(ptr, len);
        const data = files.get(name);
        if (!data) return -1n;
        const id = nextFileId++;
        openFiles.set(id, { bytes: data, pos: 0 });
        return BigInt(id);
      },
      file_read(idBig, dst, lenBig) {
        const f = openFiles.get(Number(idBig));
        if (!f) return -1n;
        const n = Math.min(Number(lenBig), f.bytes.length - f.pos);
        if (n > 0) {
          new Uint8Array(memory.buffer, Number(dst), n).set(f.bytes.subarray(f.pos, f.pos + n));
          f.pos += n;
        }
        return BigInt(n);
      },
      file_seek(idBig, offBig, whence) {
        const f = openFiles.get(Number(idBig));
        if (!f) return -1n;
        const off = Number(offBig);
        let p = whence === 0 ? off : whence === 1 ? f.pos + off : f.bytes.length + off;
        if (p < 0) p = 0;
        f.pos = p;
        return 0n;
      },
      file_tell(idBig) {
        const f = openFiles.get(Number(idBig));
        return f ? BigInt(f.pos) : -1n;
      },
      file_close(idBig) {
        openFiles.delete(Number(idBig));
        return 0;
      },
      exit(code) {
        exitCode = Number(code);
        exitResolve();
        throw new SiluExit(exitCode);
      },
    },
  };

  async function instantiate(bytes) {
    const obj = await WebAssembly.instantiate(bytes, imports);
    memory = obj.instance.exports.memory;
    const run = (async () => {
      try {
        obj.instance.exports.silu_main();
        if (exitCode === null) exitCode = 0;
      } catch (e) {
        if (!(e instanceof SiluExit)) {
          stderr.push(new TextEncoder().encode(`host: trap: ${e.message}\n${e.stack || ""}\n`));
          if (exitCode === null) exitCode = 1;
        }
      }
      exitResolve();
      return {
        exitCode,
        stdout: concatU8(stdout),
        stderr: concatU8(stderr),
      };
    })();
    return { module: { exports: obj.instance.exports, done: run } };
  }

  return { instantiate };
}

class SiluExit extends Error {
  constructor(code) {
    super(`exit ${code}`);
    this.code = code;
  }
}

/* ---------- CLI ---------- */

const isMain = typeof process !== "undefined" && process.argv[1] && import.meta.url.endsWith(process.argv[1].split("/").pop());
if (isMain) {
  const { readFileSync } = await import("node:fs");
  const argv = process.argv.slice(2);
  const wasmPath = argv[0];
  let stdin = new Uint8Array();
  const files = new Map();
  for (let i = 1; i < argv.length; i++) {
    if (argv[i] === "--file") {
      const [name, path] = argv[i + 1].split("=");
      files.set(name, new Uint8Array(readFileSync(path)));
      i++;
    } else if (argv[i] === "--stdin-data") {
      stdin = new TextEncoder().encode(argv[i + 1]);
      i++;
    } else {
      stdin = new Uint8Array(readFileSync(argv[i]));
    }
  }
  const { done } = await runWasm({ wasmPath, stdin, files });
  const r = await done;
  process.stdout.write(r.stdout);
  process.stderr.write(r.stderr);
  process.exit(r.exitCode ?? 1);
}

export { cFormatDouble, cStrtod }; // unit-test surface
