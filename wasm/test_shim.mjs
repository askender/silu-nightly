// test_shim.mjs - JS shim vs real C library: fmt_double and strtod.
//
//   clang wasm/test_shim_ref.c -o /tmp/shim_ref && /tmp/shim_ref > /tmp/shim_ref.txt
//   node wasm/test_shim.mjs /tmp/shim_ref.txt
//
// Every value is compared BIT-EXACT (hex of the f64) and every rendered
// string byte-exact against the platform C library.

import { readFileSync } from "node:fs";
import { cFormatDouble, cStrtod } from "./shim/host.mjs";

const lines = readFileSync(process.argv[2], "utf8").split("\n").filter(Boolean);
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
    const prec = spec === "g17" || spec === "e17" ? 17 : spec === "g6" || spec === "f6" || spec === "e6" ? 6 : -1;
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
