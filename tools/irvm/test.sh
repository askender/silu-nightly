#!/bin/sh
# irvm differential test: silu-irvm vs the reference ir_interp on the
# int-only probe corpus. Every probe must produce identical stdout and
# exit codes on both planes.
set -e
REPO=$(cd "$(dirname "$0")/../.." && pwd)
IRVM="$REPO/tools/irvm/target/release/silu-irvm"
INTERP="${IR_INTERP:-/tmp/ir_interp_O2}"
FE="$REPO/silu_fe"
PROBES="${*:-/tmp/irvm_p/c_and_or.si /tmp/irvm_p/fib.si /tmp/irvm_p/loops.si /tmp/irvm_p/unary.si /tmp/irvm_p/pow.si /tmp/irvm_p/boolint.si}"
pass=0; fail=0
for f in $PROBES; do
  "$FE" < "$f" > /tmp/irvm_probe.json
  a=$(timeout 60 "$INTERP" < /tmp/irvm_probe.json 2>&1); arc=$?
  b=$(timeout 60 "$IRVM" < /tmp/irvm_probe.json 2>&1); brc=$?
  if [ "$a" = "$b" ] && [ "$arc" = "$brc" ]; then
    pass=$((pass+1))
  else
    fail=$((fail+1))
    echo "FAIL $(basename $f): interp[$arc]=$(echo "$a" | tr '\n' ' ') vs irvm[$brc]=$(echo "$b" | tr '\n' ' ')"
  fi
done
echo "irvm differential: $pass pass, $fail fail"
[ "$fail" = 0 ]
