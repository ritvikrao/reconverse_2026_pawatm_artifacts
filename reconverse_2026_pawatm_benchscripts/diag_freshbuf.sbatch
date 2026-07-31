#!/bin/bash
#SBATCH --job-name=fresh
#SBATCH --account=mzu-delta-cpu
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=128
#SBATCH --exclusive
#SBATCH --time=00:20:00
#SBATCH --output=/u/rao1/bench_results/pingpong_shm/fresh-%j.out
# Does -freshbuf (never forward a peer-owned persistent buffer) avoid the
# fault?  Repeated, because the crash was not deterministic across sizes.
set -x
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/u/rao1/charm_reconverse/lib
export PMI_MAX_KVS_ENTRIES=512
export LCI_ATTR_PACKET_SIZE=8192
SHM=/u/rao1/reconverse_main/build_shm/tests/persistent_pingpong/reconverse_persistent_pingpong
LOG=/u/rao1/bench_results/pingpong_shm/raw/diag_freshbuf.log
: > "$LOG"
for mode in "forward:" "freshbuf:-freshbuf"; do
  name=${mode%%:*}; flag=${mode#*:}
  for trial in 1 2 3 4 5; do
    echo "=== $name trial $trial ===" >> "$LOG"
    timeout 90 srun --mpi=cray_shasta -N 1 -n 2 --ntasks-per-node=2 \
      --cpus-per-task=2 --cpu-bind=cores "$SHM" +ppn 1 +lci_ndevices 1 \
      $flag 200 16 262144 2 >> "$LOG" 2>&1
    echo "  rc=$?" >> "$LOG"
  done
done
echo "FRESH DIAG DONE"
