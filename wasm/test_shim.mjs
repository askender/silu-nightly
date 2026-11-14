// test_shim.mjs - JS shim vs real C library: fmt_double and strtod.
//
//   clang wasm/test_shim_ref.c -o /tmp/shim_ref && /tmp/shim_ref > /tmp/shim_ref.txt
//   node wasm/test_shim.mjs /tmp/shim_ref.txt
//
// Every value is compared BIT-EXACT (hex of the f64) and every rendered
// string byte-exact against the platform C library.

import { readFileSync, existsSync, statSync, openSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { cFormatDouble, cStrtod } from "./shim/host.mjs";

const REPO = new URL("..", import.meta.url).pathname;
const REF = "/tmp/shim_ref.txt";
// regenerate when the reference C source is newer than the data file:
// an existsSync-only check kept a STALE reference alive after
// test_shim_ref.c gained cases, so the new cases silently never ran
// (the same existsSync-cache lesson test_run.mjs already fixed)
if (
  !existsSync(REF) ||
  statSync(REPO + "wasm/test_shim_ref.c").mtimeMs > statSync(REF).mtimeMs
) {
  // ground truth from the REAL C library (test_shim_ref.c)
  execFileSync("clang", [REPO + "wasm/test_shim_ref.c", "-o", "/tmp/shim_ref"], { stdio: "inherit" });
  execFileSync("/tmp/shim_ref", { stdio: ["ignore", openSync(REF, "w"), "inherit"] });
}
const lines = readFileSync(REF, "utf8").split("\n").filter(Boolean);
const bitsOf = (v) => {
  const b = new Uint8Array(8);
  new DataView(b.buffer).setFloat64(0, v);
  return [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
};
const render = (hex, spec, prec) => {
  const dv = new DataView(new Uint8Array([...hex.matchAll(/../g)].map((h) => parseInt(h[0] + h[1], 16))).buffer);
  return cFormatDouble(dv.getFloat64(0), spec[0], prec);
};

let pass = 0;
const fails = [];
for (const line of lines) {
  const parts = line.split("|");
  if (parts[0] === "STR") {
    const [, text, hex, consumed] = parts;
    const bytes = [...text].map((c) => c.charCodeAt(0) & 0xff);
    const r = cStrtod(new Uint8Array(bytes), 0, bytes.length);
    const ok = bitsOf(r.value) === hex && r.consumed === Number(consumed);
    if (ok) pass++;
    else fails.push(`STR ${JSON.stringify(text)}: want bits=${hex} consumed=${consumed}, got bits=${bitsOf(r.value)} consumed=${r.consumed}`);
  } else {
    const [spec, hex, want] = parts;
    const prec = spec === "g17" || spec === "e17" ? 17 : spec === "g6" || spec === "f6" || spec === "e6" ? 6 : spec === "g5" ? 5 : spec === "e0" ? 0 : -1;
    const got = render(hex, spec, prec);
    if (got === want) pass++;
    else fails.push(`${spec} ${hex}: want ${JSON.stringify(want)}, got ${JSON.stringify(got)}`);
  }
}
console.log(`--- shim gate: ${pass}/${lines.length} match the C library ---`);
if (fails.length) {
  for (const f of fails.slice(0, 20)) console.log("FAIL", f);
  if (fails.length > 20) console.log(`... ${fails.length - 20} more`);
  process.exit(1);
}
