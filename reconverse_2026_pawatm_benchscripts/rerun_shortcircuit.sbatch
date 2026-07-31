#!/bin/bash
#SBATCH --job-name=metg_sc
#SBATCH --account=mzu-delta-cpu
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=128
#SBATCH --exclusive
#SBATCH --time=00:55:00
#SBATCH --output=/u/rao1/bench_results/run_shortcircuit/slurm-%j.out

# Clean METG sweep, with the three confounds found in the previous runs removed:
#
#   1. Optimisation.  All five drivers are now -O3.  charmc's -optimize expands
#      to CMK_CXX_OPTIMIZE = -O2 on both Charm++ builds, so Charm++/old-Converse,
#      Charm++/Reconverse and Converse were previously a full level below MPI
#      and Reconverse.  libcore (-O3 -mavx2 -mfma) is shared by all five.
#   2. Placement.  Every single-process run is confined to cores 0..P via
#      taskset, one CCX of one socket, instead of letting slurm and each
#      runtime's +setcpuaffinity negotiate it.  Placement was worth 4x on
#      fine-granularity overhead and 33% on the coarse point.
#   3. Clock state.  7 repetitions instead of 5, so the analyser's slow-state
#      filter still leaves a usable sample after discarding contaminated ones.
#
# Reconverse is built from `main`.

set -x
export PATH=/u/rao1/mpishim:$PATH
OUT=/u/rao1/bench_results/run_shortcircuit
mkdir -p "$OUT/raw"

# Record the placement actually obtained, so the pinning can be verified rather
# than assumed.
source /u/rao1/bench_scripts/common.sh
{
  for p in 1 2 4 8; do
    echo "=== pinning check, $p PE(s): expecting cores $(pinset "$p") ==="
    $SRUN -N 1 -n 1 --ntasks-per-node=1 --cpus-per-task=$((p + 1)) --cpu-bind=none \
      taskset -c "$(pinset "$p")" bash -c 'grep Cpus_allowed_list /proc/self/status'
  done
} > "$OUT/raw/pinning_check.log" 2>&1

REPS=7 /u/rao1/bench_scripts/run_peak.sh   "$OUT"
REPS=7 /u/rao1/bench_scripts/run_taskbench.sh "$OUT"

echo "DONE"
