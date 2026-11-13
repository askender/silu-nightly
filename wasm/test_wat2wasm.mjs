// test_wat2wasm.mjs - wat2wasm assembler gate: for every backend-emitted
// WAT (wasm/examples + benchmarks through the real fe -> backend pipe),
// the self-hosted wat2wasm.wasm must assemble the EXACT same wasm64
// binary as the wabt CLI (the differential oracle, TODO #5).
//
//   node wasm/test_wat2wasm.mjs [prog.si ...]
//
// Prereqs: repo-root ./silu_fe (native frontend), /tmp/wasm_backend_native
// (built via `silu build selfhost/wasm_backend.si`), wat2wasm CLI on PATH,
// wasm/artifacts/wat2wasm.wasm (built via `python wasm/build.py wat2wasm`).

import { readFileSync, readdirSync, writeFileSync, existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { runWasm } from "./shim/host.mjs";

const REPO = new URL("..", import.meta.url).pathname;
const dec = new TextDecoder();

const argv = process.argv.slice(2);
const files = argv.length
  ? argv
  : [
      ...readdirSync(REPO + "wasm/examples").filter((f) => f.endsWith(".si")).map((f) => "wasm/examples/" + f),
      ...readdirSync(REPO + "benchmarks").filter((f) => f.endsWith(".si")).map((f) => "benchmarks/" + f),
    ].sort();

let pass = 0;
const failures = [];
for (const f of files) {
  const p = REPO + f;
  if (!existsSync(p)) continue;
  try {
    const src = readFileSync(p);
    // si -> IR JSON -> WAT (the same pipe the playground uses)
    const json = execFileSync(REPO + "silu_fe", { input: src, maxBuffer: 1 << 26 });
    const wat = execFileSync("/tmp/wasm_backend_native", { input: json, maxBuffer: 1 << 26 });
    // oracle: wabt assembles the same WAT
    const watPath = "/tmp/w2w_prog.wat";
    const refPath = "/tmp/w2w_prog_ref.wasm";
    writeFileSync(watPath, wat);
    execFileSync("wat2wasm", [watPath, "-o", refPath], { timeout: 120000 });
    const ref = readFileSync(refPath);
    // candidate: the self-hosted assembler, WAT on stdin, hex on stdout
    const { done } = await runWasm({
      wasmBytes: new Uint8Array(readFileSync(REPO + "wasm/artifacts/wat2wasm.wasm")),
      stdin: new Uint8Array(wat),
    });
    const r = await done;
    if (r.exitCode !== 0) throw new Error("wat2wasm exited " + r.exitCode + " " + dec.decode(r.stderr).slice(0, 80));
    const hex = dec.decode(r.stdout).replace(/[^0-9a-fA-F]/g, "");
    const mine = Buffer.from(hex, "hex");
    if (mine.equals(ref)) {
      pass++;
      console.log(`PASS ${f} (byte-identical vs wabt, ${ref.length}B)`);
    } else {
      let d = -1;
      for (let i = 0; i < Math.min(mine.length, ref.length); i++) {
        if (mine[i] !== ref[i]) { d = i; break; }
      }
      throw new Error(`bytes differ: mine ${mine.length}B wabt ${ref.length}B first-diff ${d}`);
    }
  } catch (e) {
    failures.push(f);
    console.log(`FAIL ${f}: ${String(e.message).slice(0, 160)}`);
  }
}
console.log(`--- wat2wasm gate: ${pass}/${files.length} byte-identical vs wabt ---`);
if (failures.length) {
  console.log("failures:", failures.join(", "));
  process.exit(1);
}
