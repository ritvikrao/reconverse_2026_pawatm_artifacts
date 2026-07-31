#!/bin/bash
# Adaptive queue-polling benchmarks: Reconverse (adaptation on and off) against
# the original Converse, 1 node / 1 process, 4 and 8 PEs.
#
# All runs are single-process, so the network backend has nothing to progress:
# +no_progress_polling leaves pollProgress unregistered rather than letting it
# hold a slot in the polling table and cost a call per trip.
#
# Usage: run_adaptive.sh <output-dir>
source "$(dirname "$0")/common.sh"

OUT=${1:?usage: run_adaptive.sh <output-dir>}
mkdir -p "$OUT/raw"

AB=/u/rao1/adaptive_bench
PES=${PES:-"4 8"}
REPS=${REPS:-3}

# benchmark 1
RING_SWEEP=${RING_SWEEP:-"0 1 2 4 8 16 32 64"}
RING_M=${RING_M:-2000}
RING_PHASES=${RING_PHASES:-8}
RING_WARMUP=${RING_WARMUP:-3}

# benchmark 2
XY_M=${XY_M:-500}
XY_ITERS=${XY_ITERS:-5}
XY_PPS=${XY_PPS:-4}
XY_STEPS=${XY_STEPS:-9}

# Reconverse takes +pe; Converse (SMP Charm++ build) takes +ppn.
run_reconv() { local p=$1; shift
  $SRUN -N 1 -n 1 --ntasks-per-node=1 --cpus-per-task=$((p + 2)) --cpu-bind=none \
    "$@" +pe "$p" +setcpuaffinity +no_progress_polling
}
run_conv() { local p=$1; shift
  $SRUN -N 1 -n 1 --ntasks-per-node=1 --cpus-per-task=$((p + 2)) --cpu-bind=none \
    "$@" +ppn "$p" +setcpuaffinity
}

log="$OUT/raw/adaptive_ring.log"
: > "$log"
for rep in $(seq 1 "$REPS"); do
  for p in $PES; do
    for cfg in adaptive hitrate static converse; do
      echo "=== ring cfg $cfg pes $p rep $rep ===" >> "$log"
      case $cfg in
        adaptive) run_reconv "$p" "$AB/reconverse_adapt_ring" \
                    -m "$RING_M" -phases "$RING_PHASES" -warmup "$RING_WARMUP" \
                    -sweep "$RING_SWEEP" ;;
        hitrate)  run_reconv "$p" "$AB/reconverse_adapt_ring" +poll_adapt_mode hitrate \
                    -m "$RING_M" -phases "$RING_PHASES" -warmup "$RING_WARMUP" \
                    -sweep "$RING_SWEEP" ;;
        static)   run_reconv "$p" "$AB/reconverse_adapt_ring" +no_adaptive_polling \
                    -m "$RING_M" -phases "$RING_PHASES" -warmup "$RING_WARMUP" \
                    -sweep "$RING_SWEEP" ;;
        converse) run_conv "$p" "$AB/converse_adapt_ring" \
                    -m "$RING_M" -phases "$RING_PHASES" -warmup "$RING_WARMUP" \
                    -sweep "$RING_SWEEP" ;;
      esac >> "$log" 2>&1 || echo "!!! FAILED ring $cfg pe=$p rep=$rep" | tee -a "$log"
    done
  done
done
echo "ring log -> $log"

log="$OUT/raw/adaptive_xy.log"
: > "$log"
for rep in $(seq 1 "$REPS"); do
  for p in $PES; do
    for cfg in adaptive hitrate static converse; do
      echo "=== xy cfg $cfg pes $p rep $rep ===" >> "$log"
      case $cfg in
        adaptive) run_reconv "$p" "$AB/reconverse_adapt_xy" \
                    -m "$XY_M" -iters "$XY_ITERS" -phases_per_step "$XY_PPS" \
                    -steps "$XY_STEPS" ;;
        hitrate)  run_reconv "$p" "$AB/reconverse_adapt_xy" +poll_adapt_mode hitrate \
                    -m "$XY_M" -iters "$XY_ITERS" -phases_per_step "$XY_PPS" \
                    -steps "$XY_STEPS" ;;
        static)   run_reconv "$p" "$AB/reconverse_adapt_xy" +no_adaptive_polling \
                    -m "$XY_M" -iters "$XY_ITERS" -phases_per_step "$XY_PPS" \
                    -steps "$XY_STEPS" ;;
        converse) run_conv "$p" "$AB/converse_adapt_xy" \
                    -m "$XY_M" -iters "$XY_ITERS" -phases_per_step "$XY_PPS" \
                    -steps "$XY_STEPS" ;;
      esac >> "$log" 2>&1 || echo "!!! FAILED xy $cfg pe=$p rep=$rep" | tee -a "$log"
    done
  done
done
echo "xy log -> $log"
