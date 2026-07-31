#!/bin/bash
#SBATCH --job-name=diag1pe
#SBATCH --account=mzu-delta-cpu
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=128
#SBATCH --exclusive
#SBATCH --time=00:25:00
#SBATCH --output=/u/rao1/bench_results/run_ab/diag1pe-%j.out
#
# At 1 PE, Reconverse never reaches the node's fast clock state (~55 us/task at
# the coarsest, pure-compute point) in any of 7 repetitions across three
# sweeps.  Its floor is 69.3 -- a third state no other system shows, and the
# others are cleanly bimodal at 55/74.  An earlier diagnostic, run BEFORE
# taskset pinning was introduced, had Reconverse at 58.3 against Converse's
# 56.1.  So: is the 69.3 caused by the pinning, by +setcpuaffinity, or is it
# intrinsic?  Vary each independently at the coarsest granularity only.
set -x
export PATH=/u/rao1/mpishim:$PATH
source /u/rao1/bench_scripts/common.sh
LOG=/u/rao1/bench_results/run_ab/raw/diag_1pe.log
: > "$LOG"
COARSE="-kernel compute_bound -iter 16384 -type stencil_1d -steps 1000 -width 1"

run() {  # name, cpus-per-task, taskset-spec ("-" for none), then command
  local name=$1 cpus=$2 ts=$3; shift 3
  for rep in 1 2 3 4 5; do
    echo "=== $name rep=$rep ===" >> "$LOG"
    if [ "$ts" = "-" ]; then
      $SRUN -N 1 -n 1 --ntasks-per-node=1 --cpus-per-task="$cpus" --cpu-bind=none \
        "$@" $COARSE >> "$LOG" 2>&1
    else
      $SRUN -N 1 -n 1 --ntasks-per-node=1 --cpus-per-task="$cpus" --cpu-bind=none \
        taskset -c "$ts" "$@" $COARSE >> "$LOG" 2>&1
    fi
  done
}

R=$BIN_RECONVERSE
C=$BIN_CONVERSE

run "recon_taskset01_affin"    2  0-1 "$R" +pe 1 +setcpuaffinity +lci_ndevices 8
run "recon_taskset01_noaffin"  2  0-1 "$R" +pe 1 +lci_ndevices 8
run "recon_notaskset_affin"    2  -   "$R" +pe 1 +setcpuaffinity +lci_ndevices 8
run "recon_notaskset_noaffin"  2  -   "$R" +pe 1 +lci_ndevices 8
run "recon_taskset07_affin"    8  0-7 "$R" +pe 1 +setcpuaffinity +lci_ndevices 8
run "recon_taskset01_1dev"     2  0-1 "$R" +pe 1 +setcpuaffinity +lci_ndevices 1
run "conv_taskset01_affin"     2  0-1 "$C" +ppn 1 +setcpuaffinity
run "conv_notaskset_affin"     2  -   "$C" +ppn 1 +setcpuaffinity

echo "DIAG1PE DONE"
