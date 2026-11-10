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

import { readFileSync, writeFileSync } from "node:fs";

/* ---------- C-like double formatting (%f / %e / %g) ----------
 * Byte-compatibility target: glibc/Apple libc printf. JS toFixed /
 * toExponential are correctly rounded (dtoa-backed), exponent width and
 * trailing-zero stripping are handled here to match C. */

const scratch = new DataView(new ArrayBuffer(8));

function cFormatDouble(v, spec, prec) {
  if (prec < 0) prec = 6;
  scratch.setFloat64(0, v);
  const negative = scratch.getUint8(0) >> 7 === 1;
  const abs = Math.abs(v);
  let body;
  if (Number.isNaN(abs)) body = "nan";
  else if (abs === Infinity) body = "inf";
  else if (spec === "f") {
    body = abs.toFixed(prec);
  } else if (spec === "e" || spec === "E") {
    body = fixExp(abs.toExponential(prec));
  } else {
    // %g / %G: precision = significant digits; e-form iff exp < -4 || exp >= P
    const P = prec === 0 ? 1 : prec;
    const expStr = abs.toExponential(P - 1); // "d.ddde±x", X from here
    const X = parseInt(expStr.split("e")[1], 10);
    if (X >= -4 && X < P) {
      body = stripZeros(abs.toFixed(P - 1 - X));
    } else {
      body = stripZeros(fixExp(expStr));
    }
  }
  const sign = negative && !Number.isNaN(abs) ? "-" : negative ? "-" : "";
  // NaN: C prints sign only for negative nan bit pattern; JS NaN has no
  // sign - rely on the bit we already read.
  return sign + body;
}

function fixExp(s) {
  // JS: "1.5e+0" / "1e-2"  ->  C: "1.5e+00" / "1.000000e-02"
  const [m, e] = s.split("e");
  const xi = parseInt(e, 10);
  const sign = xi < 0 ? "-" : "+";
  const aw = String(Math.abs(xi)).padStart(2, "0");
  return `${m}e${sign}${aw}`;
}

function stripZeros(s) {
  if (!s.includes(".")) return s;
  s = s.replace(/0+$/, "");
  if (s.endsWith(".")) s = s.slice(0, -1);
  return s;
}

/* ---------- C strtod prefix matcher ----------
 * [ws][+-](digits[.digits?][eE...] | inf | infinity | nan) ; correctly
 * rounded conversion comes from parseFloat on the matched slice. */

const latin1Dec = new TextDecoder("latin1");
const latin1 = (bytes) => latin1Dec.decode(bytes);

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

export async function runWasm({ wasmPath, stdin = new Uint8Array(), files = new Map(), args = [] }) {
  const { instantiate } = await makeHost(files, stdin);
  const bytes = readFileSync(wasmPath);
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
    Buffer.from(memory.buffer, Number(ptr), Number(len)).toString("latin1");
  const out = (fd, ptr, len) => {
    const chunk = Buffer.from(memory.buffer, Number(ptr), Number(len));
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
        stderr.push(Buffer.from(`shim die: ${msg}\n`));
        exitCode = 70;
        exitResolve();
        throw new SiluExit(70);
      },
      write(fd, ptr, len) {
        out(Number(fd), ptr, len);
      },
      fmt_double(buf, cap, v, spec, prec) {
        const s = cFormatDouble(Number(v), String.fromCharCode(Number(spec)), Number(prec));
        const bytes = Buffer.from(s, "latin1");
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
          stderr.push(Buffer.from(`host: trap: ${e.message}\n${e.stack || ""}\n`));
          if (exitCode === null) exitCode = 1;
        }
      }
      exitResolve();
      return {
        exitCode,
        stdout: Buffer.concat(stdout),
        stderr: Buffer.concat(stderr),
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

const isMain = process.argv[1] && import.meta.url.endsWith(process.argv[1].split("/").pop());
if (isMain) {
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
      stdin = new Uint8Array(Buffer.from(argv[i + 1]));
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
