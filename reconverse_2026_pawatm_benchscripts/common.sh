#!/bin/bash
# Shared setup for the METG / ULT benchmark runs on NCSA Delta (AMD EPYC 7763).

export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/u/rao1/charm_reconverse/lib

# Reconverse / LCI settings requested for the Reconverse-backed runs.
export PMI_MAX_KVS_ENTRIES=512
export LCI_ATTR_PACKET_SIZE=8192

TB=/u/rao1/task-bench

BIN_MPI=$TB/mpi/nonblock
BIN_CHARM_OLD=$TB/charm++_oldconv/benchmark
BIN_CHARM_RECONV=$TB/charm++_reconv/benchmark
BIN_RECONVERSE=$TB/reconverse/build/task_bench
# Same driver built against reconverse `main`, i.e. without the CcdCallBacks
# short-circuit.  Carried as a separate system so the two variants are measured
# at the same points in the same sweep: comparing across sweeps cannot support
# a 5-10% claim, because Converse -- whose code did not change at all -- moved
# by up to 12% between two consecutive runs.
BIN_RECONVERSE_MAIN=$TB/reconverse/build_main/task_bench
BIN_CONVERSE=$TB/converse/task_bench
BIN_KERNEL=$TB/kernel_bench/main

ULT_RECONV_SCHED=/u/rao1/reconverse/build/tests/ult_bench/reconverse_sched_rate
ULT_RECONV_CTX=/u/rao1/reconverse/build/tests/ult_bench/reconverse_ctxswitch
ULT_CONV_SCHED=/u/rao1/ult_bench_converse/converse_sched_rate
ULT_CONV_CTX=/u/rao1/ult_bench_converse/converse_ctxswitch

SRUN="srun --mpi=cray_shasta"

# ---------------------------------------------------------------------------
# Launchers.  $1 is the number of PEs; the rest are task-bench arguments.
#
# MPI uses one rank per PE.  Charm++/Converse/Reconverse put every PE in a
# single process, as requested, so those launch one rank and ask the runtime
# for N worker threads.
#
# PLACEMENT IS PINNED EXPLICITLY, and this matters more than it looks.
# Previously each launcher passed --cpus-per-task=(P+1) --cpu-bind=none and let
# slurm choose the cpuset and the runtime's +setcpuaffinity choose within it.
# That left placement dependent on the shape of the enclosing allocation:
# rerunning the identical sweep under a different salloc/sbatch shape moved the
# fine-granularity overhead by 4x while leaving the compute-bound coarse point
# unchanged, which is the signature of PEs landing further apart rather than of
# anything in the runtimes.  Widening the cpuset alone was worth 33% (1 PE at
# the coarsest point: 5.84e-2 s inside 2 CPUs vs 7.78e-2 s inside 10).
#
# So every system is now confined to the SAME contiguous core range, cores
# 0..P, which on this node is one CCX of one socket for P <= 8 -- the PEs share
# an L3 and cannot migrate across the NUMA boundary.  The runtimes' own
# +setcpuaffinity then maps worker i onto core i inside that range, so the
# mapping is identical for Charm++, Converse and Reconverse rather than
# negotiated per-system.
# ---------------------------------------------------------------------------

# Cores 0..p-1 for p ranks/workers, plus core p for a comm thread where the
# runtime has one.  Kept identical across systems so the comparison is fair
# even though Reconverse does not spawn a comm thread.
pinset() { echo "0-$1"; }

launch_mpi() {
  local p=$1; shift
  # rank i -> core i, explicitly, rather than letting --cpu-bind=cores decide.
  local map; map=$(seq -s, 0 $((p - 1)))
  $SRUN -N 1 -n "$p" --ntasks-per-node="$p" --cpu-bind=map_cpu:"$map" \
    "$BIN_MPI" "$@"
}

# Charm++ SMP: +ppn worker threads plus a separate comm thread in one process.
launch_charm_old() {
  local p=$1; shift
  $SRUN -N 1 -n 1 --ntasks-per-node=1 --cpus-per-task=$((p + 1)) --cpu-bind=none \
    taskset -c "$(pinset "$p")" \
    "$BIN_CHARM_OLD" +ppn "$p" +setcpuaffinity "$@"
}

launch_charm_reconv() {
  local p=$1; shift
  $SRUN -N 1 -n 1 --ntasks-per-node=1 --cpus-per-task=$((p + 1)) --cpu-bind=none \
    taskset -c "$(pinset "$p")" \
    "$BIN_CHARM_RECONV" +ppn "$p" +setcpuaffinity +lci_ndevices 8 "$@"
}

launch_converse() {
  local p=$1; shift
  $SRUN -N 1 -n 1 --ntasks-per-node=1 --cpus-per-task=$((p + 1)) --cpu-bind=none \
    taskset -c "$(pinset "$p")" \
    "$BIN_CONVERSE" +ppn "$p" +setcpuaffinity "$@"
}

launch_reconverse() {
  local p=$1; shift
  $SRUN -N 1 -n 1 --ntasks-per-node=1 --cpus-per-task=$((p + 1)) --cpu-bind=none \
    taskset -c "$(pinset "$p")" \
    "$BIN_RECONVERSE" +pe "$p" +setcpuaffinity +lci_ndevices 8 "$@"
}

# Reconverse `main`: identical in every respect except the short-circuit.
launch_reconverse_main() {
  local p=$1; shift
  $SRUN -N 1 -n 1 --ntasks-per-node=1 --cpus-per-task=$((p + 1)) --cpu-bind=none \
    taskset -c "$(pinset "$p")" \
    "$BIN_RECONVERSE_MAIN" +pe "$p" +setcpuaffinity +lci_ndevices 8 "$@"
}
