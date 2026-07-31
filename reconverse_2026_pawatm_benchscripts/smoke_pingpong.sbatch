#!/bin/bash
#SBATCH --job-name=pp_smoke
#SBATCH --account=mzu-delta-cpu
#SBATCH --partition=cpu
#SBATCH --nodes=2
#SBATCH --ntasks=256
#SBATCH --exclusive
#SBATCH --time=00:20:00
#SBATCH --output=/u/rao1/bench_results/pingpong/smoke-%j.out
set -x
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/u/rao1/charm_reconverse/lib
export PMI_MAX_KVS_ENTRIES=512
export LCI_ATTR_PACKET_SIZE=8192
RB=/u/rao1/reconverse/build_debug/tests
# tiny sweep just to prove each binary runs and prints in the expected format
for name in "converse /u/rao1/charm/benchmarks/converse/pingpong/pingpong +ppn 1" \
            "recon_normal $RB/orig-converse/pingpong/reconverse_pingpong +pe 1 +lci_ndevices 8" \
            "recon_rdma $RB/rdma_pingpong/reconverse_rdma_pingpong +pe 1 +lci_ndevices 8" \
            "recon_persist $RB/persistent_pingpong/reconverse_persistent_pingpong +pe 1 +lci_ndevices 8"; do
  set -- $name; label=$1; shift
  echo "########## $label (1 node, 2 procs) ##########"
  timeout 120 srun --mpi=cray_shasta -N 1 -n 2 --ntasks-per-node=2 --cpu-bind=cores \
    "$@" 100 16 1024 2 2>&1 | tail -12
  echo "rc=$?"
done
echo "SMOKE DONE"
