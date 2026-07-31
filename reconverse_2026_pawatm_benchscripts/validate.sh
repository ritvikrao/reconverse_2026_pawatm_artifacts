#!/bin/bash
# Small smoke test of every task-bench variant and both ULT benchmarks, to
# check the launch syntax before committing to the full sweep.
source "$(dirname "$0")/common.sh"

ARGS="-kernel compute_bound -iter 1024 -type stencil_1d -steps 20 -width 4"

run() {
  local name=$1; shift
  echo "############ $name ############"
  ( set -x; "$@" ) 2>&1 | tail -30
  echo "---- exit: ${PIPESTATUS[0]} ----"
  echo
}

run "MPI (4 ranks)"                 launch_mpi 4 $ARGS
run "Charm++ / old Converse"        launch_charm_old 4 $ARGS
run "Charm++ / Reconverse"          launch_charm_reconv 4 $ARGS
run "Converse"                      launch_converse 4 $ARGS
run "Reconverse"                    launch_reconverse 4 $ARGS

echo "############ kernel_bench ############"
$BIN_KERNEL -kernel compute_bound -iter 1024 -type trivial -steps 100 -width 4 -worker 4 2>&1 | tail -12
echo

echo "############ ULT reconverse sched_rate ############"
$SRUN -N 1 -n 1 --cpus-per-task=2 --cpu-bind=none $ULT_RECONV_SCHED +pe 1 -threads 16 -yields 100 -reps 2 2>&1 | tail -10
echo "############ ULT converse sched_rate ############"
$SRUN -N 1 -n 1 --cpus-per-task=2 --cpu-bind=none $ULT_CONV_SCHED +ppn 1 -threads 16 -yields 100 -reps 2 2>&1 | tail -10
echo "############ ULT reconverse ctxswitch ############"
$SRUN -N 1 -n 1 --cpus-per-task=2 --cpu-bind=none $ULT_RECONV_CTX +pe 1 -min_flows 2 -max_flows 16 -switches 10000 -reps 2 2>&1 | tail -10
echo "############ ULT converse ctxswitch ############"
$SRUN -N 1 -n 1 --cpus-per-task=2 --cpu-bind=none $ULT_CONV_CTX +ppn 1 -min_flows 2 -max_flows 16 -switches 10000 -reps 2 2>&1 | tail -10
