#!/bin/bash
# Measure peak compute_bound FLOP/s with task-bench's own kernel_bench, for the
# same core counts used in the METG sweep.  This is the denominator of the
# efficiency numbers (efficiency = achieved FLOP/s / peak FLOP/s).
#
# kernel_bench runs the identical kernel in a bare pthread loop with no runtime
# underneath, one thread pinned per core, so it is the runtime-overhead-free
# upper bound for that core count.
#
# Usage: run_peak.sh <output-dir>
source "$(dirname "$0")/common.sh"

OUT=${1:?usage: run_peak.sh <output-dir>}
mkdir -p "$OUT/raw"
log="$OUT/raw/kernel_bench_peak.log"
: > "$log"

for p in ${PES:-1 2 4 8}; do
  for rep in $(seq 1 ${PEAK_REPS:-15}); do
    echo "=== peak pes $p rep $rep ===" >> "$log"
    $SRUN -N 1 -n 1 --ntasks-per-node=1 --cpus-per-task=$((p + 1)) --cpu-bind=none \
      "$BIN_KERNEL" -kernel compute_bound -iter 16384 -type trivial \
      -steps 2000 -width "$p" -worker "$p" >> "$log" 2>&1 \
      || echo "!!! PEAK LAUNCH FAILED pes=$p rep=$rep" | tee -a "$log"
  done
done
echo "peak log -> $log"
