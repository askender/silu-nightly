// test_run.mjs - L1 gate: .si -> fe.wasm -> IR JSON -> interp.wasm must
// produce the same program output as the native pipeline AND as CPython
// running the same .si file directly.
//
//   node wasm/test_run.mjs [file.si ...]
//
// Native pipeline: ./silu_fe | /tmp/ir_interp_native (built from
// selfhost/ir_interp.si via ./siluc1 + clang; built automatically if
// missing). CPython runs the .si source unmodified.

import { readFileSync, readdirSync, existsSync, writeFileSync, statSync } from "node:fs";
import { execFileSync, spawnSync } from "node:child_process";
import { runWasm } from "./shim/host.mjs";

const REPO = new URL("..", import.meta.url).pathname;
const A = REPO + "wasm/artifacts";
const dec = new TextDecoder();

// native interp reference, built on demand from the self-hosted chain
const NATIVE_INTERP = "/tmp/ir_interp_native";
{
  // rebuild when the selfhost source is newer (the existsSync cache bit
  // us once: a stale binary kept failing with old bugs)
  const si = REPO + "selfhost/ir_interp.si";
  let rebuild = !existsSync(NATIVE_INTERP);
  if (!rebuild) {
    rebuild = statSync(si).mtimeMs > statSync(NATIVE_INTERP).mtimeMs;
  }
  if (rebuild) {
    // siluc1 emits the .ll TEXT on stdout - it must land in a file before
    // clang sees it (passing the text as an argv filename fails)
    const llPath = "/tmp/ir_interp.ll";
    writeFileSync(llPath, execFileSync(REPO + "siluc1", {
      input: readFileSync(si),
      maxBuffer: 1 << 26,
    }));
    execFileSync("clang", [llPath, "-o", NATIVE_INTERP], { cwd: REPO });
  }
}

// ir_interp is int-only: everything outside the subset fails LOUDLY.
// The two-pass pre-check bails with "ir_interp bail: <reason>" + exit 3
// on BOTH planes before any program output (it used to silently return
// 0s - and even HANG on float consts - which is why these examples were
// a skip list before). The full-feature run of the same examples lives
// in the L2 backend gate (test_backend.mjs).
const INTERP_LOUD = new Set(["wasm/examples/floats.si", "wasm/examples/lists.si", "wasm/examples/strings.si", "wasm/examples/dicts.si", "wasm/examples/float_ops.si", "wasm/examples/aug_sub.si", "wasm/examples/dicts_f.si", "wasm/examples/edge.si", "wasm/examples/dsbig.si", "wasm/examples/globals.si", "wasm/examples/strbuf_sem.si", "wasm/examples/stdin_demo.si", "wasm/examples/record_sem.si", "wasm/examples/and_or_nary.si"]);

const argv = process.argv.slice(2);
const files = argv.length
  ? argv
  : readdirSync(REPO + "wasm/examples")
      .filter((f) => f.endsWith(".si"))
      .map((f) => "wasm/examples/" + f)
      .sort();

let pass = 0;
let loud = 0;
const failures = [];
for (const f of files) {
  const src = new Uint8Array(readFileSync(REPO + f));
  try {
    // wasm pipeline
    const fe = await runWasm({ wasmPath: A + "/fe.wasm", stdin: src });
    const feR = await fe.done;
    if (feR.exitCode !== 0) throw new Error("fe exit " + feR.exitCode + " " + dec.decode(feR.stderr).slice(0, 120));
    const interp = await runWasm({ wasmPath: A + "/interp.wasm", stdin: feR.stdout });
    const ir = await interp.done;
    const wasmOut = dec.decode(ir.stdout);

    // native pipeline (spawnSync: loud runs exit non-zero on purpose)
    const nativeJson = execFileSync(REPO + "silu_fe", { input: src, maxBuffer: 1 << 26 });
    const nativeRun = spawnSync(NATIVE_INTERP, { input: nativeJson, maxBuffer: 1 << 26 });
    const nativeOut = nativeRun.stdout.toString();
    const nativeCode = nativeRun.status;

    if (INTERP_LOUD.has(f)) {
      if (ir.exitCode === 0) throw new Error("expected loud bail, wasm interp exited 0 with " + JSON.stringify(wasmOut.slice(0, 40)));
      if (nativeCode === 0) throw new Error("expected loud bail, native interp exited 0");
      if (!wasmOut.startsWith("ir_interp bail:")) throw new Error("wasm bail message missing: " + JSON.stringify(wasmOut.slice(0, 60)));
      if (nativeOut !== wasmOut) throw new Error(`bail messages differ: wasm=${JSON.stringify(wasmOut.slice(0, 60))} native=${JSON.stringify(nativeOut.slice(0, 60))}`);
      if (ir.exitCode !== nativeCode) throw new Error(`bail codes differ: wasm ${ir.exitCode} native ${nativeCode}`);
      loud++;
      console.log(`LOUD ${f}: ir_interp bails on both planes (${JSON.stringify(wasmOut.slice(0, 60))})`);
      continue;
    }

    if (ir.exitCode !== 0) throw new Error("interp exit " + ir.exitCode + " " + dec.decode(ir.stderr).slice(0, 120));

    // CPython
    const pyOut = execFileSync("python3", [REPO + f], { maxBuffer: 1 << 26, timeout: 300 }).toString();

    if (wasmOut === nativeOut && wasmOut === pyOut) {
      pass++;
      console.log(`PASS ${f} (${JSON.stringify(wasmOut.slice(0, 40))})`);
    } else {
      failures.push(f);
      console.log(`FAIL ${f}: wasm=${JSON.stringify(wasmOut.slice(0, 60))} native=${JSON.stringify(nativeOut.slice(0, 60))} cpython=${JSON.stringify(pyOut.slice(0, 60))}`);
    }
  } catch (e) {
    failures.push(f);
    console.log(`FAIL ${f}: ${String(e.message).slice(0, 140)}`);
  }
}
console.log(`--- wasm run gate: ${pass}/${files.length} three-way identical + ${loud} loud ---`);
if (failures.length) {
  console.log("failures:", failures.join(", "));
  process.exit(1);
}
