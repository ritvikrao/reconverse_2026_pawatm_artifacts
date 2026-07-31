#!/bin/bash
#SBATCH --job-name=metg_o3
#SBATCH --account=mzu-delta-cpu
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=128
#SBATCH --exclusive
#SBATCH --time=00:50:00
#SBATCH --output=/u/rao1/bench_results/run_o3/slurm-%j.out

# Re-run of the METG sweep after two build fixes:
#
#   1. Every Task Bench driver is now compiled -O3.  Previously the three
#      charmc-built drivers (Charm++/old-Converse, Charm++/Reconverse,
#      Converse) came out at -O2, because charmc's -optimize expands to
#      CMK_CXX_OPTIMIZE which conv-config.sh defaults to "-O2", while the MPI
#      driver hardcodes -O3 and the Reconverse driver is a CMake Release build.
#      So two of the five systems were a full optimization level above the
#      other three.
#   2. Reconverse is now built from the `main` branch rather than the
#      adaptive-queues working branch.
#
# The libcore kernel (-O3 -mavx2 -mfma) is shared by all five and was rebuilt
# too, so the FLOPs being timed are identical across systems.

set -x
export PATH=/u/rao1/mpishim:$PATH
OUT=/u/rao1/bench_results/run_o3
mkdir -p "$OUT/raw"

source /u/rao1/bench_scripts/common.sh

# ---------------------------------------------------------------------------
# Diagnostic: in the previous run Reconverse at 1 PE took 69.4 us/task at the
# COARSEST granularity (iter=16384), where a task is ~55 ms of pure compute and
# runtime overhead is under a microsecond -- every other system landed at
# 55.2-55.8 us/task, and Reconverse never once reached that state across five
# repetitions.  That is not scheduler overhead, so record what threads each
# runtime actually creates and where they are pinned.
# ---------------------------------------------------------------------------
{
  echo "### thread/affinity diagnostic, 1 PE, coarse granularity ###"
  for sys in converse reconverse; do
    echo "--- $sys ---"
    case $sys in
      converse)   BIN="$BIN_CONVERSE";   ARGS="+ppn 1 +setcpuaffinity" ;;
      reconverse) BIN="$BIN_RECONVERSE"; ARGS="+pe 1 +setcpuaffinity +lci_ndevices 8" ;;
    esac
    $SRUN -N 1 -n 1 --ntasks-per-node=1 --cpus-per-task=2 --cpu-bind=none \
      bash -c "
        $BIN $ARGS -kernel compute_bound -iter 16384 -type stencil_1d \
             -steps 1000 -width 1 & p=\$!
        sleep 4
        echo 'threads:'; ls /proc/\$p/task | wc -l
        for t in /proc/\$p/task/*; do
          printf '  tid %s  cpu %s  affinity %s  %s\n' \
            \"\$(basename \$t)\" \"\$(awk '{print \$39}' \$t/stat 2>/dev/null)\" \
            \"\$(taskset -pc \$(basename \$t) 2>/dev/null | sed 's/.*: //')\" \
            \"\$(cat \$t/comm 2>/dev/null)\"
        done
        wait \$p"
  done
} > "$OUT/raw/thread_diagnostic.log" 2>&1

# ---------------------------------------------------------------------------
# Hardware peak, then the full interleaved sweep.
# ---------------------------------------------------------------------------
/u/rao1/bench_scripts/run_peak.sh   "$OUT"
/u/rao1/bench_scripts/run_taskbench.sh "$OUT"

echo "DONE"
