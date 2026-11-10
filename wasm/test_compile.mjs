// test_compile.mjs - wasm siluc1 vs native siluc1 byte-identity gate.
//
//   node wasm/test_compile.mjs [file.si ...]
//
// Default corpus: every benchmarks/*.si and selfhost/utf8_probe.si.
// Each file: wasm siluc1.wasm output must be byte-identical to the
// native ./siluc1 output (and both exit 0). Byte-identity is the whole
// point - see docs/wasm_plan.md.

import { readFileSync, readdirSync, existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { runWasm } from "./shim/host.mjs";

const REPO = new URL("..", import.meta.url).pathname;
const WASM_BIN = REPO + "wasm/artifacts/siluc1.wasm";
const NATIVE = REPO + "siluc1";

const argv = process.argv.slice(2);
let files = argv;
if (files.length === 0) {
  // diff_harness CORPUS_LL: all benchmarks + the selfhost probes; the
  // 12k-line typed_codegen_flat stays IR-plane-only there and here.
  files = readdirSync(REPO + "benchmarks")
    .filter((f) => f.endsWith(".si"))
    .map((f) => "benchmarks/" + f);
  for (const f of ["calc.si", "strbuf_probe.si", "utf8_probe.si",
                   "ir_interp.si", "silu_fe.si"]) {
    if (existsSync(REPO + "selfhost/" + f)) files.push("selfhost/" + f);
  }
}

let pass = 0;
const failures = [];
for (const f of files) {
  const src = new Uint8Array(readFileSync(REPO + f));
  const { done } = await runWasm({ wasmPath: WASM_BIN, stdin: src });
  const r = await done;
  const native = execFileSync(NATIVE, {
    input: src,
    maxBuffer: 1 << 28,
  });
  const ok =
    r.exitCode === 0 && Buffer.compare(r.stdout, native) === 0;
  if (ok) {
    pass++;
    console.log(`PASS ${f} (${r.stdout.length}B)`);
  } else {
    failures.push(f);
    console.log(
      `FAIL ${f} wasm_exit=${r.exitCode} native=${native.length}B wasm=${r.stdout.length}B`,
    );
    if (r.stderr.length) console.log("  stderr:", r.stderr.toString().slice(0, 200));
  }
}
console.log(`--- wasm compile gate: ${pass}/${files.length} byte-identical ---`);
if (failures.length) {
  console.log("failures:", failures.join(", "));
  process.exit(1);
}
