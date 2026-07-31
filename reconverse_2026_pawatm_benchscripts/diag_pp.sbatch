#!/bin/bash
#SBATCH --job-name=pp_diag
#SBATCH --account=mzu-delta-cpu
#SBATCH --partition=cpu
#SBATCH --nodes=2
#SBATCH --ntasks=256
#SBATCH --exclusive
#SBATCH --time=00:25:00
#SBATCH --output=/u/rao1/bench_results/pingpong/diag-%j.out
# rdma_pingpong hung during smoke.  Its own CMake test runs it with no
# +lci_ndevices flag, so check whether the device count is what breaks it,
# and whether persistent (also RMA-based) has the same problem.
set -x
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/u/rao1/charm_reconverse/lib
export PMI_MAX_KVS_ENTRIES=512
export LCI_ATTR_PACKET_SIZE=8192
RB=/u/rao1/reconverse_main/build_release/tests
LOG=/u/rao1/bench_results/pingpong/raw/diag_ndevices.log
: > "$LOG"
for ver in rdma_pingpong/reconverse_rdma_pingpong persistent_pingpong/reconverse_persistent_pingpong orig-converse/pingpong/reconverse_pingpong; do
  for nd in "" "+lci_ndevices 1" "+lci_ndevices 2" "+lci_ndevices 8"; do
    for place in "1node:-N 1 -n 2 --ntasks-per-node=2" "2node:-N 2 -n 2 --ntasks-per-node=1"; do
      pl=${place%%:*}; topo=${place#*:}
      echo "=== ${ver%%/*} nd='${nd:-default}' $pl ===" >> "$LOG"
      timeout 60 srun --mpi=cray_shasta $topo --cpus-per-task=2 --cpu-bind=cores \
        "$RB/$ver" +ppn 1 $nd 50 16 1024 2 >> "$LOG" 2>&1
      echo "  rc=$?" >> "$LOG"
    done
  done
done
echo "DIAG DONE"
