#!/bin/bash
#SBATCH --job-name=pp_shm
#SBATCH --account=mzu-delta-cpu
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=128
#SBATCH --exclusive
#SBATCH --time=00:40:00
#SBATCH --output=/u/rao1/bench_results/pingpong_shm/slurm-%j.out
#
# Intra-node pingpong with LCI's experimental POSIX shared-memory transport
# (-DLCI_WITH_SHM=ON) against the same build without it.
#
# Both builds are run in the SAME job, interleaved, so the comparison is
# paired: node and clock state cancel in the ratio.  Comparing against the
# earlier non-SHM sweep instead would not support a small effect, because
# repetition spread in that run was 2-16%.
#
# Only the 1-physical-node set is run: the SHM transport is intra-node only,
# so it cannot affect the 2-node numbers.
#
# LCI_WITH_SHM=ON makes shm_enable default to true (binding.cpp:159), so no
# runtime flag is needed.  But shm_slot_size defaults to 128 bytes and the
# usable size is min(slot payload, packet payload), so by default only the
# smallest messages in the sweep can take the SHM path at all.  The last arm
# raises the slot size to cover more of the sweep.
set -x
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/u/rao1/charm_reconverse/lib
export PMI_MAX_KVS_ENTRIES=512
export LCI_ATTR_PACKET_SIZE=8192

OUT=/u/rao1/bench_results/pingpong_shm
mkdir -p "$OUT/raw"

NOSHM=/u/rao1/reconverse_main/build_release/tests
SHM=/u/rao1/reconverse_main/build_shm/tests
CONV=/u/rao1/charm/benchmarks/converse/pingpong/pingpong

ARGS="${ARGS:-1000 16 262144 2}"
REPS=${REPS:-5}
# recon_persist_shm is omitted: persistent + LCI SHM faults (SIGABRT/SIGSEGV,
# 5 of 5 trials, with and without -freshbuf).  The persistent row therefore
# comes from the non-SHM build, run here in the same job so it is still paired
# with everything else rather than carried over from another allocation.
VERSIONS="converse recon_normal recon_normal_shm recon_rdma recon_rdma_shm recon_persist recon_normal_shm8k"

launch() {  # $1 = version
  local ver=$1 bin flags
  local a="${ARGS_OVERRIDE:-$ARGS}"
  local pre=""
  case $ver in
    converse)           bin="$CONV"; flags="+ppn 1" ;;
    recon_normal)       bin="$NOSHM/orig-converse/pingpong/reconverse_pingpong"
                        flags="+ppn 1 +lci_ndevices 1" ;;
    recon_normal_shm)   bin="$SHM/orig-converse/pingpong/reconverse_pingpong"
                        flags="+ppn 1 +lci_ndevices 1" ;;
    recon_rdma)         bin="$NOSHM/rdma_pingpong/reconverse_rdma_pingpong"
                        flags="+ppn 1 +lci_ndevices 1" ;;
    recon_rdma_shm)     bin="$SHM/rdma_pingpong/reconverse_rdma_pingpong"
                        flags="+ppn 1 +lci_ndevices 1" ;;
    recon_persist)      bin="$NOSHM/persistent_pingpong/reconverse_persistent_pingpong"
                        flags="+ppn 1 +lci_ndevices 1" ;;
    recon_persist_shm)  bin="$SHM/persistent_pingpong/reconverse_persistent_pingpong"
                        flags="+ppn 1 +lci_ndevices 1" ;;
    recon_normal_shm8k) bin="$SHM/orig-converse/pingpong/reconverse_pingpong"
                        flags="+ppn 1 +lci_ndevices 1"
                        pre="LCI_ATTR_SHM_SLOT_SIZE=8192" ;;
  esac
  timeout 300 env $pre srun --mpi=cray_shasta -N 1 -n 2 --ntasks-per-node=2 \
    --cpus-per-task=2 --cpu-bind=cores "$bin" $flags $a
}

# Confirm the SHM transport is actually enabled at runtime, not just compiled.
{
  echo "### LCI shm_enable, as reported by the runtime ###"
  LCI_LOG_LEVEL=info timeout 120 srun --mpi=cray_shasta -N 1 -n 2 \
    --ntasks-per-node=2 --cpus-per-task=2 --cpu-bind=cores \
    "$SHM/orig-converse/pingpong/reconverse_pingpong" +ppn 1 +lci_ndevices 1 \
    20 16 64 2 2>&1 | grep -iE "shm|packet" | head -20
} > "$OUT/raw/shm_enabled_check.log" 2>&1

SMOKE="$OUT/raw/smoke.log"; : > "$SMOKE"; smoke_failed=0
for ver in $VERSIONS; do
  echo "=== smoke $ver ===" >> "$SMOKE"
  if ARGS_OVERRIDE="50 16 1024 2" launch "$ver" >> "$SMOKE" 2>&1; then :; else
    echo "!!! SMOKE FAILED: $ver" | tee -a "$SMOKE"; smoke_failed=1
  fi
done
[ "$smoke_failed" != 0 ] && { echo "SMOKE FAILED -- not running the sweep"; exit 1; }
echo "smoke passed for all arms"

for ver in $VERSIONS; do : > "$OUT/raw/1node_${ver}.log"; done

nver=$(set -- $VERSIONS; echo $#)
for rep in $(seq 1 "$REPS"); do
  shift_by=$(( (rep - 1) % nver ))
  ordered=$(set -- $VERSIONS; for i in $(seq 0 $((nver - 1))); do
              idx=$(( (i + shift_by) % nver + 1 )); eval echo -n "\${$idx}\ "; done)
  for ver in $ordered; do
    log="$OUT/raw/1node_${ver}.log"
    echo "=== place 1node version $ver rep $rep ===" >> "$log"
    launch "$ver" >> "$log" 2>&1 || echo "!!! FAILED $ver rep=$rep" | tee -a "$log"
  done
  echo "rep $rep of $REPS complete"
done
echo "PINGPONG SHM DONE"
