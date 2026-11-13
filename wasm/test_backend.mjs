// test_backend.mjs - L2 gate: si -> fe -> wasm_backend -> wat2wasm ->
// execute under Node; program output must equal CPython's.
//
//   node wasm/test_backend.mjs [file.si ...]
//
// Prereqs: wasm/artifacts/{fe.wasm}, /tmp/wasm_backend_native (built
// via `silu build selfhost/wasm_backend.si`), wat2wasm on PATH.

import { readFileSync, readdirSync, writeFileSync, existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { runWasm } from "./shim/host.mjs";

const REPO = new URL("..", import.meta.url).pathname;
const dec = new TextDecoder();
const enc = new TextEncoder();

const argv = process.argv.slice(2);
const files = argv.length
  ? argv
  : readdirSync(REPO + "wasm/examples")
      .filter((f) => f.endsWith(".si"))
      .map((f) => "wasm/examples/" + f)
      .sort();

let pass = 0;
const failures = [];
for (const f of files) {
  const src = readFileSync(REPO + f);
  try {
    // stdin sidecar: examples/<name>.stdin (if present) feeds BOTH the
    // wasm program and CPython - the input() pipeline under test
    const sidecar = REPO + f.replace(/\.si$/, ".stdin");
    const stdinBytes = existsSync(sidecar) ? new Uint8Array(readFileSync(sidecar)) : new Uint8Array();
    // front end: si -> IR JSON
    const json = execFileSync(REPO + "silu_fe", { input: src, maxBuffer: 1 << 26 });
    // backend: IR JSON -> WAT
    const wat = execFileSync("/tmp/wasm_backend_native", { input: json, maxBuffer: 1 << 26 });
    // wat -> wasm (memory64 is on by default in wabt >= 1.0.38)
    const watPath = "/tmp/l2_prog.wat";
    const wasmPath = "/tmp/l2_prog.wasm";
    writeFileSync(watPath, wat);
    execFileSync("wat2wasm", [watPath, "-o", wasmPath]);
    // execute
    const { done } = await runWasm({ wasmBytes: new Uint8Array(readFileSync(wasmPath)), stdin: stdinBytes });
    const r = await done;
    if (r.exitCode !== 0) throw new Error("program exit " + r.exitCode + " " + dec.decode(r.stderr).slice(0, 100));
    const out = dec.decode(r.stdout);
    const expected = execFileSync("python3", [REPO + f], { input: Buffer.from(stdinBytes), maxBuffer: 1 << 26, timeout: 120 }).toString();
    if (out === expected) {
      pass++;
      console.log(`PASS ${f} (${JSON.stringify(out.slice(0, 40))})`);
    } else {
      failures.push(f);
      console.log(`FAIL ${f}: wasm=${JSON.stringify(out.slice(0, 60))} cpython=${JSON.stringify(expected.slice(0, 60))}`);
    }
  } catch (e) {
    failures.push(f);
    console.log(`FAIL ${f}: ${String(e.message).slice(0, 140)}`);
  }
}
// artifact-level smoke: the PUBLISHED playground backend (web copy)
// must also compile a program byte-equal to CPython - guards against
// the web copies going stale while the native-path gate stays green
const webBackend = REPO + "wasm/web/backend.wasm";
if (existsSync(webBackend)) {
  try {
    // the published backend must produce the SAME WAT as the native
    // backend for the same IR JSON (the program pipeline needs wabt in
    // Node - not available - so the WAT byte-compare IS the smoke)
    const json = execFileSync(REPO + "silu_fe", {
      input: readFileSync(REPO + "wasm/examples/dicts.si"), maxBuffer: 1 << 26,
    });
    const nativeWat = execFileSync("/tmp/wasm_backend_native", { input: json, maxBuffer: 1 << 26 });
    const { done } = await runWasm({ wasmBytes: new Uint8Array(readFileSync(webBackend)), stdin: json });
    const r = await done;
    if (r.exitCode !== 0) {
      throw new Error("web backend exited " + r.exitCode + " - stderr: " + new TextDecoder().decode(r.stderr).slice(0, 100));
    }
    const webWat = r.stdout;
    if (Buffer.compare(webWat, nativeWat) === 0) {
      console.log(`PASS web/backend.wasm artifact smoke (WAT byte-identical to native, ${webWat.length} bytes)`);
    } else {
      throw new Error(`WAT differs: web ${webWat.length}B vs native ${nativeWat.length}B`);
    }
  } catch (e) {
    failures.push("web/backend.wasm artifact smoke");
    console.log(`FAIL web/backend.wasm artifact smoke: ${String(e.message).slice(0, 120)}`);
  }
}
console.log(`--- L2 backend gate: ${pass}/${files.length} match CPython ---`);
if (failures.length) {
  console.log("failures:", failures.join(", "));
  process.exit(1);
}
