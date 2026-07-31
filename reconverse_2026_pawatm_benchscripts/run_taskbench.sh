#!/bin/bash
# Task Bench METG sweep: stencil_1d, 1000 steps, task graph width == PE count,
# task granularity swept by halving -iter from 16384 down to 2.
#
# Systems are INTERLEAVED rather than run one after another.  Running each
# system's whole sweep as a contiguous block was measurably unfair on these
# nodes: over a ~20 minute sweep the node's sustained clock drifts down, so
# whichever system runs first gets the cold node.  In one such run MPI and
# Charm++/old-Converse (first in the order) finished the 1-PE coarsest point
# in ~55 ms while Converse, Reconverse and Charm++/Reconverse (later) took
# ~69-78 ms for the identical work -- an artefact of ordering, not of the
# runtimes; re-running Converse alone afterwards reproduced ~55 ms.
#
# So the loop nesting is  rep -> PE count -> granularity -> system, putting all
# five systems' launches for a given (rep, PE, iter) point adjacent in time.
# Any thermal or boost drift is then shared almost equally by all of them.
#
# Usage: run_taskbench.sh <output-dir>
source "$(dirname "$0")/common.sh"

OUT=${1:?usage: run_taskbench.sh <output-dir>}
mkdir -p "$OUT/raw"

STEPS=${STEPS:-1000}
TYPE=${TYPE:-stencil_1d}
ITERS=${ITERS:-"16384 8192 4096 2048 1024 512 256 128 64 32 16 8 4 2"}
PES=${PES:-"1 2 4 8"}
SYSTEMS=${SYSTEMS:-"mpi charm_old charm_reconv converse reconverse reconverse_main"}
REPS=${REPS:-5}

launch_for() {
  case $1 in
    mpi)           shift; launch_mpi "$@" ;;
    charm_old)     shift; launch_charm_old "$@" ;;
    charm_reconv)  shift; launch_charm_reconv "$@" ;;
    converse)      shift; launch_converse "$@" ;;
    reconverse)    shift; launch_reconverse "$@" ;;
    reconverse_main) shift; launch_reconverse_main "$@" ;;
    *) echo "unknown system $1" >&2; return 1 ;;
  esac
}

for sys in $SYSTEMS; do
  for p in $PES; do
    : > "$OUT/raw/${sys}_pe${p}.log"
  done
done

nsys=$(set -- $SYSTEMS; echo $#)

for rep in $(seq 1 "$REPS"); do
  for p in $PES; do
    for it in $ITERS; do
      # Rotate the system order every repetition so no system is permanently
      # first (and therefore permanently on the coolest silicon) at a point.
      shift_by=$(( (rep - 1) % nsys ))
      ordered=$(set -- $SYSTEMS; for i in $(seq 0 $((nsys - 1))); do
                  idx=$(( (i + shift_by) % nsys + 1 )); eval echo -n "\${$idx}\ "; done)
      for sys in $ordered; do
        log="$OUT/raw/${sys}_pe${p}.log"
        echo "=== system $sys pes $p iter $it rep $rep ===" >> "$log"
        if ! launch_for "$sys" "$p" -kernel compute_bound -iter "$it" \
             -type "$TYPE" -steps "$STEPS" -width "$p" >> "$log" 2>&1; then
          echo "!!! LAUNCH FAILED: $sys pe=$p iter=$it rep=$rep" | tee -a "$log"
        fi
      done
    done
  done
  echo "rep $rep of $REPS complete"
done
echo "sweep complete -> $OUT/raw"
