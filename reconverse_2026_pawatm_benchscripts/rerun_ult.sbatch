#!/bin/bash
#SBATCH --job-name=ult_o3
#SBATCH --account=mzu-delta-cpu
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=128
#SBATCH --exclusive
#SBATCH --time=00:30:00
#SBATCH --output=/u/rao1/bench_results/run_pinned/ult-%j.out
# ULT benchmarks rerun: the Converse ports were also being built at -O2 by
# charmc -optimize while the Reconverse originals are a CMake Release (-O3)
# build, so the two sides of that comparison were a level apart.  Both are now
# -O3, and Reconverse is rebuilt from `main`.
set -x
export PATH=/u/rao1/mpishim:$PATH
/u/rao1/bench_scripts/run_ult.sh /u/rao1/bench_results/run_pinned
echo "ULT DONE"
