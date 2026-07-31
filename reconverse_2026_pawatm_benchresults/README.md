# METG and ULT benchmark runs — NCSA Delta, AMD EPYC 7763

Result files:

* `metg_results.txt`     — Task Bench minimum effective task granularity
* `ult_results.txt`      — ULT scheduling rate and context switch cost
* `adaptive_results.txt` — adaptive queue-polling benchmarks
  (`adaptive_20260730_final/`)

`raw/` holds every benchmark's unedited stdout, delimited by `=== ... ===`
headers, so the tables can be regenerated or re-parsed differently.

## Run directories

**Use `run_ab` — it holds all three final result files, plus `FINDINGS.md`.** The other directories are earlier passes, kept only for
provenance.

| directory | what it is |
|---|---|
| `run_20260730_1155` | first pass. task-bench superseded |
| `run_20260730_final` | task-bench with 5 reps everywhere, but still run system-by-system — superseded |
| `run_20260730_interleaved` | interleaved sweep, but Charm++/Reconverse was built without `--with-production` — superseded |
| `run_20260730_production` | interleaved sweep after the `--with-production` rebuild — superseded by `run_pinned` |
| `run_o3` | `-O3` rerun under a batch allocation whose shape moved thread placement; **placement-confounded, do not use** |
| `run_pinned` | all drivers `-O3`, placement pinned, 7 reps, clock-filtered — superseded by `run_ab` |
| `run_shortcircuit` | first sweep after the `CcdCallBacks()` short-circuit; unpaired, so it cannot support the 5-10% claim — kept for provenance |
| `run_ab` | **final.** As `run_pinned`, plus Reconverse `main` carried as a sixth system so the short-circuit is measured paired at every point |

`run_ab` supersedes `run_20260730_production` for three reasons, all
documented in `run_ab/FINDINGS.md`:

1. **Optimization was not uniform.** `charmc -optimize` expands to `-O2`, not
   `-O3`, so the three charmc-built drivers (Charm++/old-Converse,
   Charm++/Reconverse, Converse) and both Converse ULT ports were a full
   optimization level below MPI and Reconverse. All are now `-O3`.
2. **Placement was uncontrolled**, and was worth 4x on fine-granularity
   overhead. Every system is now pinned to cores `0..P`.
3. **The node has at least three clock states**, and METG's self-normalization
   against each system's own coarsest run turned that into a lottery —
   Reconverse drew the slow state twice as often as Converse, which is most of
   what the apparent "Converse beats Reconverse" result was.

Charm++/Reconverse was originally built without `--with-production`, which cost
it 4-6x on METG and made it look far worse than Charm++ on old Converse. All
five systems were re-swept together rather than re-running that one system, so
the table stays internally comparable — re-running a single system on its own
would have reintroduced the ordering bias described below.

With that rebuild plus the three fixes above, the standing result is that
**Charm++ on Reconverse beats Charm++ on old Converse** at every PE count, by
8-38% on the per-task overhead floor. The earlier appearance that the ordering
inverted between the two layers did not survive controlling for optimization,
placement and clock state.

**Bare Reconverse vs bare Converse** was a wash before the `CcdCallBacks()`
short-circuit (branch `ccd-shortcircuit`); with it, Reconverse is ahead at 2 and
4 PE (0.82x, 0.88x) and level at 1 PE. The short-circuit itself is worth a
paired, sign-tested 5-10% at 1-4 PE and is not detectable at 8 PE.

**Open item:** at 1 PE, Reconverse runs the identical pure-compute kernel ~25%
slower than every other system (69.3 us/task vs 55.4), reproducibly, with
pinning, `+setcpuaffinity`, cgroup width and LCI device count all excluded by
controlled test. It does not appear at 2+ PE and does not affect the per-task
overhead floor. Cause unidentified — see `run_ab/FINDINGS.md`.

Two measurement problems had to be fixed to get trustworthy task-bench numbers,
both caused by the node's clock behaviour rather than by any runtime:

1. **Too few repetitions at coarse granularity.** The upstream experiment
   scripts ramp repetitions — 1 at the coarsest point, rising to 5 at the
   finest. But the coarse points set the efficiency scale, and they vary
   20-33% run to run here. Fixed by running 7 repetitions at every
   granularity.

2. **Sweep ordering bias.** Running each system's whole sweep as a contiguous
   block gave whichever system went first a cool node. Over a ~20 minute
   sweep the sustained clock drifts down, so MPI and Charm++/old-Converse
   (first in the order) recorded ~55 ms on the 1-PE coarsest point while
   Converse, Reconverse and Charm++/Reconverse (later) recorded ~69-78 ms for
   identical work. Re-running Converse alone afterwards reproduced ~55 ms,
   confirming the cause. Fixed by interleaving all five systems at every
   measurement point and rotating which one leads on each repetition.

The remaining variation is bimodal — the node intermittently sits in a lower
clock state — so points are reported as the **median** of the surviving
repetitions, after whole repetitions that ran in the slow state are discarded on
the evidence of their pure-compute coarse point (~17% of runs). A mean would be dragged around by however
many slow reps a configuration caught, and a best-of would reward whichever
system got lucky. Each table row carries a `spread` column showing
(worst-best)/best so the effect stays visible.

The METG curve is normalised against a **shared** per-PE-count reference (the
25th percentile of all systems' coarse points), not against each system's own
coarsest run. Self-normalisation was the original choice and it made METG a
lottery: that one run is the measurement most exposed to clock state, so a
system that happened to measure its own reference slow was scored generously
ever after. The absolute view is kept as a secondary `vs peak` column, and two
normalisation-free cross-checks (coarse-point agreement, per-task overhead
floor) are reported alongside.

The ULT runs were unaffected — each PE already reports best-of-5 internally,
and both layers were measured back to back at every point — and were not
repeated.

## What was built, and where

Task Bench, all against a freshly rebuilt `core` (AVX2/FMA enabled for Zen3):

| system | binary | built with |
|---|---|---|
| MPI | `task-bench/mpi/nonblock` | cray-mpich 8.1.32 via the Cray `CC` wrapper |
| Charm++ / old Converse | `task-bench/charm++_oldconv/benchmark` | `charmc` from `charm/mpi-linux-x86_64-smp` |
| Charm++ / Reconverse | `task-bench/charm++_reconv/benchmark` | `charmc` from `charm_reconverse/reconverse-linux-x86_64` |
| Reconverse | `task-bench/reconverse/build/task_bench` | CMake, `RECONVERSE_ROOT=/u/rao1/reconverse` (branch `ccd-shortcircuit`), LCIv2 backend |
| Reconverse (main) | `task-bench/reconverse/build_main/task_bench` | same, against the `main` worktree `/u/rao1/reconverse_main` — the A/B baseline |
| Converse | `task-bench/converse/task_bench` | `charmc -language converse++`, same `main.cc` as the Reconverse build |

ULT benchmarks:

| layer | binary |
|---|---|
| Reconverse | `reconverse/build/tests/ult_bench/reconverse_{sched_rate,ctxswitch}` |
| Converse | `ult_bench_converse/converse_{sched_rate,ctxswitch}` |

### Two build notes

`charmc` on both Charm++ trees invokes a bare `mpicxx`, which in the current
login environment resolves to a non-functional anaconda wrapper. The Charm
installs were left untouched; `mpicxx`/`mpicc` shims that `exec CC`/`exec cc`
were placed on `PATH` for the duration of compilation only. That matches how
both Charm trees were originally configured
(`CMAKE_CXX_COMPILER=/opt/cray/pe/craype/2.7.34/bin/CC`).

The pre-existing `mpi/nonblock` had been linked against a spack OpenMPI 4.1.6.
It was rebuilt against cray-mpich so that `srun --mpi=cray_shasta` is the
correct launcher for it.

## Reproducing

```
salloc --no-shell -N 1 -n 128 --exclusive --account=mzu-delta-cpu \
       --time=02:00:00 --partition=cpu
export SLURM_JOB_ID=<jobid>

bash bench_scripts/run_peak.sh      <outdir>   # efficiency denominator
bash bench_scripts/run_taskbench.sh <outdir>   # the METG sweep
bash bench_scripts/run_ult.sh       <outdir>   # the ULT benchmarks

python3 bench_scripts/analyze.py     <outdir> -o <outdir>/metg_results.txt
python3 bench_scripts/analyze_ult.py <outdir> -o <outdir>/ult_results.txt
```

`bench_scripts/common.sh` holds the launch lines and the environment
(`LD_LIBRARY_PATH`, `PMI_MAX_KVS_ENTRIES=512`, `LCI_ATTR_PACKET_SIZE=8192`,
`+lci_ndevices 8` for the Reconverse-backed runs).

Set `RAMP_REPS=1` on `run_taskbench.sh` to get the upstream repetition ramp
instead of 5 everywhere.


## Adaptive queue polling

`adaptive_20260730_final/adaptive_results.txt`, from the benchmarks in
`/u/rao1/adaptive_bench/` and the adaptation added on the reconverse
`register-queues` branch.

The scheduler walks a 64-slot table of queue-polling functions; slots held ==
polling frequency. Each PE counts messages pulled per queue and every 10 trips
around the table re-apportions the slots, with a floor of one slot per
registered queue. Runtime flags added: `+no_adaptive_polling`,
`+poll_adapt_mode count|hitrate`, `+no_progress_polling`.

Two weighting rules are compared:

* `count`   — slots proportional to messages pulled. This is the specified
  rule and the build default.
* `hitrate` — slots proportional to messages pulled / times polled. Added
  because `count` is self-referential: a queue can only be drained as often as
  it is polled, so for a busy queue the count is largely a measure of how many
  slots it already had.

Runs are 1 node / 1 process, 4 and 8 PEs, with progress polling left
unregistered since a single process has no network traffic to progress.

**Comparisons are paired.** The node drifts between clock states, so a whole
repetition can be 30-40% faster than the next for every configuration alike.
The four configurations are launched back to back inside each repetition, so
the within-repetition ratio is drift-free; the tables report the median of
those ratios plus their min..max range. Where the range straddles zero the
effect is smaller than the noise and should not be read as a result.

Headline: Reconverse beats Converse by 12-72% everywhere regardless of
adaptation. Adaptation itself helps on benchmark 2 and on benchmark 1 at 4 PEs,
but *hurts* on benchmark 1 at 8 PEs in the mixed regime (-17% to -31%), because
allocating slots by message volume starves the shared node queue that carries
the latency-critical ring. See the "Reading these tables" section of the
results file.
