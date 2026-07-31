#!/bin/bash
#SBATCH --job-name=pingpong
#SBATCH --account=mzu-delta-cpu
#SBATCH --partition=cpu
#SBATCH --nodes=2
#SBATCH --ntasks=256
#SBATCH --exclusive
#SBATCH --time=00:40:00
#SBATCH --output=/u/rao1/bench_results/pingpong/slurm-%j.out
#
# Pingpong: 8 configurations = 2 placements x 4 versions.
#
#   placement "1node" : 2 processes, 1 PE each, both on one physical node
#   placement "2node" : 2 processes, 1 PE each, one per physical node
#
#   converse       old Converse  (charm/benchmarks/converse/pingpong)
#   recon_normal   Reconverse, message pingpong
#   recon_rdma     Reconverse, explicit RDMA get on CmiNcpyBuffer
#   recon_persist  Reconverse, persistent channel (one-sided put into
#                  pre-registered receive buffers)
#
# Every version is run at every point before any version is repeated, and the
# order is rotated each repetition.  Running one version's whole sweep as a
# block was worth ~25% on this machine in the task-bench work, purely from
# where in the run it landed.
set -x
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/u/rao1/charm_reconverse/lib
export PMI_MAX_KVS_ENTRIES=512
export LCI_ATTR_PACKET_SIZE=8192

OUT=/u/rao1/bench_results/pingpong
mkdir -p "$OUT/raw"

RB=/u/rao1/reconverse_main/build_release/tests
CONV=/u/rao1/charm/benchmarks/converse/pingpong/pingpong

ARGS="${ARGS:-1000 16 262144 2}"
# +lci_ndevices 8 CANNOT be used for the RDMA and persistent versions: the
# one-sided get aborts inside LCI's OFI backend with
#   post_get_impl:388 <lci:Assert failed: false> err : Invalid argument
# at any device count above 1, because the memory region is registered against
# one device and the get is posted on another.  All four versions therefore run
# at 1 device so the comparison stays like for like; with one PE per process
# there is no concurrency for extra devices to exploit anyway.
ND=${ND:-1}
REPS=${REPS:-5}
VERSIONS="converse recon_normal recon_rdma recon_persist"
# Supplementary: the message path at the 8 devices originally requested, to
# quantify what the device count is worth where it does work.
VERSIONS="$VERSIONS recon_normal_nd8"

# Both processes get 2 cores: the Converse SMP build runs a worker plus a
# comm thread, Reconverse runs one PE and no comm thread, and giving them the
# same allocation keeps the placement identical rather than advantaging
# whichever needs fewer.
launch() {  # $1 = placement, $2 = version
  local place=$1 ver=$2 topo
  case $place in
    1node) topo="-N 1 -n 2 --ntasks-per-node=2" ;;
    2node) topo="-N 2 -n 2 --ntasks-per-node=1" ;;
  esac
  case $ver in
    converse)      bin="$CONV"; flags="+ppn 1" ;;
    recon_normal)  bin="$RB/orig-converse/pingpong/reconverse_pingpong"
                   flags="+ppn 1 +lci_ndevices $ND" ;;
    recon_rdma)    bin="$RB/rdma_pingpong/reconverse_rdma_pingpong"
                   flags="+ppn 1 +lci_ndevices $ND" ;;
    recon_persist) bin="$RB/persistent_pingpong/reconverse_persistent_pingpong"
                   flags="+ppn 1 +lci_ndevices $ND" ;;
    recon_normal_nd8) bin="$RB/orig-converse/pingpong/reconverse_pingpong"
                   flags="+ppn 1 +lci_ndevices 8" ;;
  esac
  local a="${ARGS_OVERRIDE:-$ARGS}"
  timeout 300 srun --mpi=cray_shasta $topo --cpus-per-task=2 \
    --cpu-bind=verbose,cores "$bin" $flags $a
}

# Smoke first: a 50-iteration, 16-1024 byte run of each version at each
# placement.  persistent_pingpong is new code and has never run, so prove all
# eight configurations start, finish and print before spending the allocation
# on the real sweep.
SMOKE="$OUT/raw/smoke.log"
: > "$SMOKE"
smoke_failed=0
for place in 1node 2node; do
  for ver in $VERSIONS; do
    echo "=== smoke $place $ver ===" >> "$SMOKE"
    if ARGS_OVERRIDE="50 16 1024 2" launch "$place" "$ver" >> "$SMOKE" 2>&1; then
      n=$(grep -c "microseconds one-way" "$SMOKE")
      echo "  (cumulative result lines: $n)" >> "$SMOKE"
    else
      echo "!!! SMOKE FAILED: $place $ver" | tee -a "$SMOKE"
      smoke_failed=1
    fi
  done
done
if [ "$smoke_failed" != 0 ]; then
  echo "SMOKE FAILED -- not running the sweep"
  exit 1
fi
echo "smoke passed for all 8 configurations"

for place in 1node 2node; do
  for ver in $VERSIONS; do
    : > "$OUT/raw/${place}_${ver}.log"
  done
done

nver=$(set -- $VERSIONS; echo $#)
for rep in $(seq 1 "$REPS"); do
  for place in 1node 2node; do
    shift_by=$(( (rep - 1) % nver ))
    ordered=$(set -- $VERSIONS; for i in $(seq 0 $((nver - 1))); do
                idx=$(( (i + shift_by) % nver + 1 )); eval echo -n "\${$idx}\ "; done)
    for ver in $ordered; do
      log="$OUT/raw/${place}_${ver}.log"
      echo "=== place $place version $ver rep $rep ===" >> "$log"
      launch "$place" "$ver" >> "$log" 2>&1 \
        || echo "!!! FAILED $place $ver rep=$rep" | tee -a "$log"
    done
  done
  echo "rep $rep of $REPS complete"
done

echo "PINGPONG DONE"
