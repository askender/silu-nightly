#!/bin/sh
# Cross-plane bytecode identity gate: the same silu IR compiled by the
# Rust irvm and the Silu twin (selfhost/ir_vm.si) must produce the
# byte-identical instruction stream. Divergence here means one twin
# drifted from the shared bytecode spec (monty-style: u8 opcode +
# W(u16 LE)/K(u8) suffixes, label backpatching, [module][funcs] layout).
set -e
REPO=$(cd "$(dirname "$0")/../.." && pwd)
IRVM="$REPO/tools/irvm/target/release/silu-irvm"
FE="$REPO/silu_fe"
PROBES="${*:-$REPO/tools/irvm/probes/c_and_or.si $REPO/tools/irvm/probes/fib.si $REPO/tools/irvm/probes/loops.si $REPO/tools/irvm/probes/unary.si $REPO/tools/irvm/probes/pow.si $REPO/tools/irvm/probes/boolint.si $REPO/tools/irvm/probes/bool_lit.si $REPO/tools/irvm/probes/fibseq.si $REPO/tools/irvm/probes/fib10.si $REPO/tools/irvm/probes/dbl.si}"

# the twin's native binary: build once if absent (compiler output is
# content-checked by the driver cache, so a stale binary cannot survive
# a source edit silently)
TWIN="${IRVM_TWIN:-/tmp/ir_vm_native}"
if [ ! -x "$TWIN" ]; then
  echo "building Silu twin -> $TWIN"
  ${PY312:-python3} -m silu build "$REPO/selfhost/ir_vm.si" -o "$TWIN"
fi

pass=0; fail=0
for f in $PROBES; do
  "$FE" < "$f" > /tmp/irvm_bdiff.json
  a=$(IRVM_DUMP=1 "$IRVM" < /tmp/irvm_bdiff.json)
  printf '@dump\n' > /tmp/irvm_bdump.in
  cat /tmp/irvm_bdiff.json >> /tmp/irvm_bdump.in
  b=$("$TWIN" < /tmp/irvm_bdump.in)
  if [ "$a" = "$b" ] && [ -n "$a" ]; then
    pass=$((pass+1))
  else
    fail=$((fail+1))
    echo "BYTECODE MISMATCH $(basename $f):"
    echo "  rust: $(echo "$a" | head -c 120)"
    echo "  silu: $(echo "$b" | head -c 120)"
  fi
done
echo "bytecode identity: $pass pass, $fail fail"
[ "$fail" = 0 ]
