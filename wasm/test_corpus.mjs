// test_corpus.mjs - L2 corpus gate (formalized from the /tmp probe):
// every non-dynamic benchmark runs FULL SIZE through fe -> wasm_backend
// -> wat2wasm -> silu_host, and its output must be byte-identical to
// CPython's on the same stdin. jsonparse x2 are pyobj subset-external:
// CPython parses the generated document fine while the wasm side must
// fail LOUDLY (nonzero exit, never wrong bytes).
//
//   node wasm/test_corpus.mjs [name ...]
//
// Prereqs: repo-root silu_fe, wat2wasm on PATH; /tmp/wasm_backend_native
// (auto-built from selfhost/wasm_backend.si via PY312 when missing).
// Timings per benchmark - knucleotide@200000 and wordcount@300000 are
// the str-ABI canaries (linear since the length-prefix + extend work).

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { runWasm } from "./shim/host.mjs";

const REPO = new URL("..", import.meta.url).pathname;
const dec = new TextDecoder();

const PASS_NAMES = ["arith", "dict", "fannkuch", "fib", "float", "jsonparse",
  "knucleotide", "list", "mandelbrot", "nbody", "spectral", "string",
  "trees", "wordcount"];
// jsonparse + jsonparse_json: the reference plane is the silu
// interpreter (CPython has no auto-record-constructor semantics);
// jsonparse_json additionally needs the Json builtins - still loud
const INTERP_REF = new Set(["jsonparse"]);
const LOUD_NAMES = ["jsonparse_json"];

const argv = process.argv.slice(2);
const names = argv.length ? argv : [...PASS_NAMES, ...LOUD_NAMES];

// backend native binary, auto-built on demand (silu build needs the
// llvmlite-bearing python: PY312, see AGENTS.md)
const BACKEND = "/tmp/wasm_backend_native";
if (!existsSync(BACKEND)) {
  const PY = process.env.PY312 || "python3";
  console.log(`building ${BACKEND} via ${PY} -m silu build ...`);
  execFileSync(PY, ["-m", "silu", "build", REPO + "selfhost/wasm_backend.si", "-o", BACKEND],
    { stdio: ["ignore", "ignore", "inherit"] });
}

function toWasm(name) {
  const src = readFileSync(REPO + "benchmarks/" + name + ".si");
  const json = execFileSync(REPO + "silu_fe", { input: src, maxBuffer: 1 << 26 });
  const wat = execFileSync(BACKEND, { input: json, maxBuffer: 1 << 26 });
  const watPath = `/tmp/corpus_${name}.wat`;
  const wasmPath = `/tmp/corpus_${name}.wasm`;
  writeFileSync(watPath, wat);
  execFileSync("wat2wasm", [watPath, "-o", wasmPath]);
  return wasmPath;
}

let pass = 0, loudOk = 0;
const failures = [];
for (const name of names) {
  const isLoud = LOUD_NAMES.includes(name);
  try {
    // the shared JSON document for the jsonparse pair (deterministic
    // bytes from the checked-in generator)
    let stdinBytes = new Uint8Array();
    if (name === "jsonparse" || name === "jsonparse_json") {
      stdinBytes = new Uint8Array(execFileSync("python3", [REPO + "scripts/gen_json_input.py"], { maxBuffer: 1 << 24 }));
    }
    const wasmPath = toWasm(name);
    const t0 = Date.now();
    const { done } = await runWasm({ wasmBytes: new Uint8Array(readFileSync(wasmPath)), stdin: stdinBytes });
    const r = await done;
    const ms = Date.now() - t0;
    const out = dec.decode(r.stdout);
    if (isLoud) {
      // loud trap expected at the class-constructor call site
      if (r.exitCode !== 0) {
        loudOk++;
        console.log(`LOUDOK ${name}: wasm trapped (exit ${r.exitCode}) as expected (Json builtins subset-external)`);
      } else {
        failures.push(name);
        console.log(`LOUDFAIL ${name}: exit 0 with ${JSON.stringify(out.slice(0, 40))} - expected a loud trap`);
      }
      continue;
    }
    if (r.exitCode !== 0) {
      failures.push(name);
      console.log(`TRAP ${name}: exit ${r.exitCode} ${dec.decode(r.stderr).slice(0, 120)}`);
      continue;
    }
    let expected;
    if (INTERP_REF.has(name)) {
      const PY = process.env.PY312 || "python3";
      expected = execFileSync(PY, ["-m", "silu", "interpret", REPO + "benchmarks/" + name + ".si"],
        { input: Buffer.from(stdinBytes), maxBuffer: 1 << 26, timeout: 600000 }).toString();
    } else {
      expected = execFileSync("python3", [REPO + "benchmarks/" + name + ".si"],
        { input: Buffer.from(stdinBytes), maxBuffer: 1 << 26, timeout: 600000 }).toString();
    }
    if (out === expected) {
      pass++;
      console.log(`PASS ${name}: byte-identical (wasm exec ${ms}ms)`);
    } else {
      const gl = out.splitlines ? out.splitlines() : out.split("\n");
      const el = expected.split("\n");
      let nd = 0;
      for (let i = 0; i < Math.max(gl.length, el.length); i++) {
        if (gl[i] !== el[i]) nd++;
      }
      failures.push(name);
      console.log(`DIFF ${name}: ${nd} lines differ (wasm exec ${ms}ms); first: ${JSON.stringify(gl[0])} vs ${JSON.stringify(el[0])}`);
    }
  } catch (e) {
    failures.push(name);
    console.log(`FAIL ${name}: ${String(e.message).slice(0, 140)}`);
  }
}
console.log(`--- corpus gate: ${pass}/${PASS_NAMES.length} byte-identical + ${loudOk}/${LOUD_NAMES.length} loud`);
if (failures.length) {
  console.log("failures:", failures.join(", "));
  process.exit(1);
}
