#!/bin/bash
# ULT benchmarks: scheduling (dispatch) rate and ULT-to-ULT context switch cost
# vs the number of concurrent flows, for Reconverse and for the original
# Converse inside Charm++.
#
# Usage: run_ult.sh <output-dir>
source "$(dirname "$0")/common.sh"

OUT=${1:?usage: run_ult.sh <output-dir>}
mkdir -p "$OUT/raw"

SCHED_THREADS=${SCHED_THREADS:-"1 2 4 8 16 32 64 128 256 512 1024 2048"}
SCHED_YIELDS=${SCHED_YIELDS:-1000}
SCHED_REPS=${SCHED_REPS:-5}

CTX_MIN_FLOWS=${CTX_MIN_FLOWS:-2}
CTX_MAX_FLOWS=${CTX_MAX_FLOWS:-4096}
CTX_SWITCHES=${CTX_SWITCHES:-200000}
CTX_REPS=${CTX_REPS:-5}

ULT_PES=${ULT_PES:-"1 4"}

# Reconverse takes +pe for the PE count, Converse (SMP Charm++ build) +ppn.
run_reconv() { local p=$1; shift
  $SRUN -N 1 -n 1 --ntasks-per-node=1 --cpus-per-task=$((p + 1)) --cpu-bind=none \
    "$@" +pe "$p" +setcpuaffinity +lci_ndevices 8
}
run_conv() { local p=$1; shift
  $SRUN -N 1 -n 1 --ntasks-per-node=1 --cpus-per-task=$((p + 1)) --cpu-bind=none \
    "$@" +ppn "$p" +setcpuaffinity
}

# ---------------------------- scheduling rate ----------------------------
log="$OUT/raw/ult_sched_rate.log"
: > "$log"
for p in $ULT_PES; do
  for t in $SCHED_THREADS; do
    for layer in reconverse converse; do
      echo "=== ult sched_rate layer $layer pes $p threads $t ===" >> "$log"
      case $layer in
        reconverse) run_reconv "$p" "$ULT_RECONV_SCHED" \
                      -threads "$t" -yields "$SCHED_YIELDS" -reps "$SCHED_REPS" ;;
        converse)   run_conv "$p" "$ULT_CONV_SCHED" \
                      -threads "$t" -yields "$SCHED_YIELDS" -reps "$SCHED_REPS" ;;
      esac >> "$log" 2>&1 \
        || echo "!!! FAILED sched_rate $layer pe=$p threads=$t" | tee -a "$log"
    done
  done
done
echo "sched_rate log -> $log"

# --------------------------- context switch ---------------------------
log="$OUT/raw/ult_ctxswitch.log"
: > "$log"
for p in $ULT_PES; do
  for layer in reconverse converse; do
    echo "=== ult ctxswitch layer $layer pes $p ===" >> "$log"
    case $layer in
      reconverse) run_reconv "$p" "$ULT_RECONV_CTX" \
                    -min_flows "$CTX_MIN_FLOWS" -max_flows "$CTX_MAX_FLOWS" \
                    -switches "$CTX_SWITCHES" -reps "$CTX_REPS" ;;
      converse)   run_conv "$p" "$ULT_CONV_CTX" \
                    -min_flows "$CTX_MIN_FLOWS" -max_flows "$CTX_MAX_FLOWS" \
                    -switches "$CTX_SWITCHES" -reps "$CTX_REPS" ;;
    esac >> "$log" 2>&1 \
      || echo "!!! FAILED ctxswitch $layer pe=$p" | tee -a "$log"
  done
done
echo "ctxswitch log -> $log"
