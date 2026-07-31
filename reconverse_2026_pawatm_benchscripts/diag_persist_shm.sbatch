#!/bin/bash
#SBATCH --job-name=pshm_diag
#SBATCH --account=mzu-delta-cpu
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=128
#SBATCH --exclusive
#SBATCH --time=00:25:00
#SBATCH --output=/u/rao1/bench_results/pingpong_shm/diag-%j.out
# persistent_pingpong segfaults on the SHM build.  Is that my new benchmark,
# or the persistent+SHM combination generally?  The repo's own persistent test
# is the control: if it crashes too, the benchmark is not at fault.
set -x
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/u/rao1/charm_reconverse/lib
export PMI_MAX_KVS_ENTRIES=512
export LCI_ATTR_PACKET_SIZE=8192
SHM=/u/rao1/reconverse_main/build_shm/tests
NOSHM=/u/rao1/reconverse_main/build_release/tests
LOG=/u/rao1/bench_results/pingpong_shm/raw/diag_persist_shm.log
: > "$LOG"

run() { echo "=== $1 ===" >> "$LOG"; shift
        timeout 90 srun --mpi=cray_shasta -N 1 -n 2 --ntasks-per-node=2 \
          --cpus-per-task=2 --cpu-bind=cores "$@" >> "$LOG" 2>&1
        echo "  rc=$?" >> "$LOG"; }

# 1. Control: the repo's own persistent test, SHM build vs non-SHM build.
run "repo persistent test, NO shm"  "$NOSHM/persistent/reconverse_persistent" +ppn 1 +lci_ndevices 1
run "repo persistent test, SHM"     "$SHM/persistent/reconverse_persistent"   +ppn 1 +lci_ndevices 1

# 2. Is SHM the trigger, or merely the build?  Same SHM binary, SHM disabled.
LCI_ATTR_SHM_ENABLE=0 run "persistent_pingpong, SHM build, shm DISABLED" \
  "$SHM/persistent_pingpong/reconverse_persistent_pingpong" +ppn 1 +lci_ndevices 1 50 16 1024 2

# 3. Where does it die?  Sizes at and below the 128-byte SHM slot limit.
for mx in 16 32 64 128 256; do
  run "persistent_pingpong, SHM, sizes 16..$mx" \
    "$SHM/persistent_pingpong/reconverse_persistent_pingpong" +ppn 1 +lci_ndevices 1 20 16 $mx 2
done

# 4. Backtrace.
echo "=== gdb backtrace ===" >> "$LOG"
timeout 150 srun --mpi=cray_shasta -N 1 -n 2 --ntasks-per-node=2 --cpus-per-task=2 \
  --cpu-bind=cores gdb -q -batch -ex run -ex "bt 25" --args \
  "$SHM/persistent_pingpong/reconverse_persistent_pingpong" +ppn 1 +lci_ndevices 1 20 16 64 2 \
  >> "$LOG" 2>&1
echo "DIAG DONE"
