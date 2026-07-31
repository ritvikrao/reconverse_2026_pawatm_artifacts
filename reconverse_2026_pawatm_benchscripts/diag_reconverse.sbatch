#!/bin/bash
#SBATCH --job-name=metg_diag
#SBATCH --account=mzu-delta-cpu
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=128
#SBATCH --exclusive
#SBATCH --time=00:30:00
#SBATCH --output=/u/rao1/bench_results/run_o3/diag-%j.out

# Why is Reconverse ~25-28% slower than every other system at the COARSEST
# granularity, where the task is ~55 us of pure libcore compute and the runtime
# handles one message per task?  A runtime cannot cost 16 us per message here,
# so the kernel itself must be running slower inside the Reconverse process.
#
# Two candidates, both testable:
#   A. `+lci_ndevices 8` crowds the cgroup.  The launcher asks for
#      --cpus-per-task=(PEs+1), which is 2 CPUs at 1 PE.  If LCI spawns
#      per-device threads, 8 devices land on 2 CPUs alongside the compute PE.
#   B. Core placement: +setcpuaffinity pins the PE somewhere worse than the
#      Charm++ SMP build does.
#
# Sweep device count and cgroup width independently, at the coarsest
# granularity only, and record the thread inventory for each.

set -x
export PATH=/u/rao1/mpishim:$PATH
source /u/rao1/bench_scripts/common.sh
OUT=/u/rao1/bench_results/run_o3
mkdir -p "$OUT/raw"
LOG="$OUT/raw/diag_reconverse.log"
: > "$LOG"

COARSE="-kernel compute_bound -iter 16384 -type stencil_1d -steps 1000"

# --- A: device count x cgroup width, 1 PE and 8 PEs, 3 reps each ------------
for p in 1 8; do
  for cpus in $((p + 1)) $((p + 9)); do
    for nd in 1 2 8; do
      for rep in 1 2 3; do
        echo "=== reconverse pe=$p cpus=$cpus ndevices=$nd rep=$rep ===" >> "$LOG"
        $SRUN -N 1 -n 1 --ntasks-per-node=1 --cpus-per-task="$cpus" --cpu-bind=none \
          "$BIN_RECONVERSE" +pe "$p" +setcpuaffinity +lci_ndevices "$nd" \
          $COARSE -width "$p" >> "$LOG" 2>&1
      done
    done
  done
  # Converse reference at the same shape
  for rep in 1 2 3; do
    echo "=== converse pe=$p cpus=$((p + 1)) rep=$rep ===" >> "$LOG"
    $SRUN -N 1 -n 1 --ntasks-per-node=1 --cpus-per-task=$((p + 1)) --cpu-bind=none \
      "$BIN_CONVERSE" +ppn "$p" +setcpuaffinity $COARSE -width "$p" >> "$LOG" 2>&1
  done
  # Reconverse with no affinity pinning at all
  for rep in 1 2 3; do
    echo "=== reconverse-noaffinity pe=$p cpus=$((p + 1)) ndevices=8 rep=$rep ===" >> "$LOG"
    $SRUN -N 1 -n 1 --ntasks-per-node=1 --cpus-per-task=$((p + 1)) --cpu-bind=none \
      "$BIN_RECONVERSE" +pe "$p" +lci_ndevices 8 $COARSE -width "$p" >> "$LOG" 2>&1
  done
done

# --- B: thread inventory --------------------------------------------------
# 1000 tasks x 55 us is only ~56 ms, so the earlier probe raced the process
# exit.  -steps 100000 makes the run ~5.6 s, long enough to inspect.
TLOG="$OUT/raw/diag_threads.log"
: > "$TLOG"
for cfg in "converse 1 $BIN_CONVERSE +ppn" "reconverse 1 $BIN_RECONVERSE +pe"; do
  set -- $cfg; name=$1; p=$2; bin=$3; flag=$4
  extra=""; [ "$name" = reconverse ] && extra="+lci_ndevices 8"
  echo "=== $name pe=$p ===" >> "$TLOG"
  $SRUN -N 1 -n 1 --ntasks-per-node=1 --cpus-per-task=$((p + 1)) --cpu-bind=none \
    bash -c "
      $bin $flag $p +setcpuaffinity $extra -kernel compute_bound -iter 16384 \
        -type stencil_1d -steps 100000 -width $p >/dev/null 2>&1 &
      pid=\$!
      sleep 3
      echo \"thread count: \$(ls /proc/\$pid/task 2>/dev/null | wc -l)\"
      for t in /proc/\$pid/task/*; do
        [ -r \$t/stat ] || continue
        echo \"  tid \$(basename \$t) comm=\$(cat \$t/comm) last_cpu=\$(awk '{print \$39}' \$t/stat) allowed=\$(grep Cpus_allowed_list \$t/status | awk '{print \$2}')\"
      done
      kill \$pid 2>/dev/null; wait 2>/dev/null" >> "$TLOG" 2>&1
done

echo "DIAG DONE"
