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
    const { done } = await runWasm({ wasmBytes: new Uint8Array(readFileSync(wasmPath)), stdin: new Uint8Array() });
    const r = await done;
    if (r.exitCode !== 0) throw new Error("program exit " + r.exitCode + " " + dec.decode(r.stderr).slice(0, 100));
    const out = dec.decode(r.stdout);
    const expected = execFileSync("python3", [REPO + f], { maxBuffer: 1 << 26, timeout: 120 }).toString();
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
    const src = readFileSync(REPO + "wasm/examples/dicts.si");
    const { done } = await runWasm({ wasmBytes: new Uint8Array(readFileSync(webBackend)), stdin: src });
    const r = await done;
    const json = execFileSync(REPO + "silu_fe", { input: src, maxBuffer: 1 << 26 });
    const wat = execFileSync("/tmp/wasm_backend_native", { input: json, maxBuffer: 1 << 26 });
    const watPath = "/tmp/web_smoke.wat";
    writeFileSync(watPath, wat);
    execFileSync("wat2wasm", [watPath, "-o", "/tmp/web_smoke.wasm"]);
    const rr = await runWasm({ wasmBytes: new Uint8Array(readFileSync("/tmp/web_smoke.wasm")), stdin: new Uint8Array() });
    const rr2 = await rr.done;
    const out = new TextDecoder().decode(rr2.stdout);
    const expected = execFileSync("python3", [REPO + "wasm/examples/dicts.si"], { maxBuffer: 1 << 26, timeout: 120 }).toString();
    if (out === expected) {
      console.log(`PASS web/backend.wasm artifact smoke (dicts.si via L2 backend)`);
    } else {
      failures.push("web/backend.wasm artifact smoke");
      console.log(`FAIL web/backend.wasm artifact smoke: wasm=${JSON.stringify(out.slice(0, 60))} cpython=${JSON.stringify(expected.slice(0, 60))}`);
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
