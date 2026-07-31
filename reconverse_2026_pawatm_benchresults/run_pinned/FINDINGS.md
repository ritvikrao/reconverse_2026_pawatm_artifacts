# METG: why the Reconverse/Converse ordering looked inverted between layers

Answering: *"it seems weird that Charm++ on Reconverse has a generally higher
METG than Charm++ on Converse, but standalone Converse beats standalone
Reconverse"* — plus the request to confirm Task Bench is built at maximum
optimization.

Short answer: **there is no real inversion.** Three independent confounds were
riding on the earlier numbers. With all three controlled, Charm++ on Reconverse
is consistently *better* than Charm++ on old Converse, and bare Reconverse
versus bare Converse is a wash.

## 1. Optimization was not uniform (fixed)

`charmc -optimize` does **not** mean `-O3`. It expands to `CMK_CXX_OPTIMIZE`,
which both Charm++ builds default to `-O2`:

    charm/mpi-linux-x86_64-smp/tmp/conv-config.sh:32
        [ -z "$CMK_C_OPTIMIZE" ] && CMK_C_OPTIMIZE="-O2"

Meanwhile `mpi/Makefile` hardcodes `-O3` and the Reconverse driver is a CMake
`Release` build. So three of the five drivers were a full optimization level
below the other two:

| driver | before | after |
|---|---|---|
| MPI | -O3 | -O3 |
| Charm++/old-Converse | **-O2** | -O3 |
| Charm++/Reconverse | **-O2** | -O3 |
| Converse | **-O2** | -O3 |
| Reconverse | -O3 | -O3 |

Fixed in `task-bench/{converse,reconverse,charm++,charm++_oldconv,charm++_reconv}/Makefile`
and `ult_bench_converse/Makefile`, verified in the emitted compiler command
lines rather than only in the Makefiles. `libcore` (`-O3 -mavx2 -mfma`) is
shared by all five and was rebuilt, so the FLOPs being timed are identical;
`kernel_bench` peak reproduced to within 1% on a different node, confirming the
kernel itself did not change.

## 2. Placement was not controlled (fixed)

The launchers passed `--cpus-per-task=(P+1) --cpu-bind=none` and let slurm pick
the cpuset and each runtime's `+setcpuaffinity` pick within it. That made the
result depend on the shape of the enclosing allocation. Rerunning the identical
sweep under a different allocation shape moved fine-granularity overhead by
**4x** while leaving the compute-bound coarse point unchanged — the signature of
PEs landing further apart, not of anything in the runtimes. Widening the cpuset
alone was worth 33% (1 PE coarse: 5.84e-2 s in 2 CPUs vs 7.78e-2 s in 10).

Every system is now confined to the same contiguous range, cores `0..P` — one
CCX of one socket at these PE counts. Verified per run in
`raw/pinning_check.log`.

## 3. The node has at least three clock states (filtered)

The coarsest granularity point is a pure-compute control: a task is ~55 us of
`libcore` work and the runtime handles one message per task, so every system
must agree on it. It does not. At 1 PE the 35 coarse runs split cleanly into
55.2–55.8 us (n=15) and 69.3–74.7 us (n=20) — a 33% gap that no runtime causes.
At 4 PE there is also a rare *faster* state (14.2–14.5 us against a main cluster
at 17.4–18.9) which only Converse and Charm++/old-Converse happened to catch.

This matters disproportionately because METG(50%) is self-normalized against
each system's *own* coarsest run — the single measurement most exposed to clock
state. A system that measured its reference slow is scored generously ever
after. Two changes:

* whole repetitions whose coarse point exceeds the node reference by >10% are
  discarded for that system at every granularity (18.6% of runs here);
* the efficiency denominator is now a **shared** reference per PE count (25th
  percentile of all coarse runs), so no system normalizes against its own
  lottery ticket.

The 25th percentile rather than the minimum: keying off the minimum would have
discarded 30 of 34 runs at 4 PE, because the minimum there *is* the rare boost
state.

**This was the dominant confound.** In the earlier production data, Reconverse
caught the slow state in 8 of 20 (system, PE, rep) combinations against
Converse's 4 — which is most of what "standalone Converse beats standalone
Reconverse" ever was.

## Results (7 repetitions, pinned, filtered)

Per-task overhead floor, us/task — median over iter = 8, 4, 2, where the kernel
contributes <0.03 us. No normalization, so this is immune to confound 3:

| system | 1 PE | 2 PE | 4 PE | 8 PE |
|---|---|---|---|---|
| MPI | 0.200 | 0.362 | 0.313 | 0.164 |
| Charm++ (old Converse) | 0.777 | 0.998 | 0.754 | 0.720 |
| Charm++ (Reconverse) | 0.792 | 0.913 | 0.674 | 0.463 |
| Converse | 0.416 | 0.613 | 0.493 | 0.303 |
| Reconverse | – | 0.614 | 0.456 | 0.372 |

Residual coarse-point offsets still bias some columns, and correcting each ratio
by its own offset (both shown in `metg_results.txt`, cross-check 1):

| ratio | 1 PE | 2 PE | 4 PE | 8 PE |
|---|---|---|---|---|
| Reconverse / Converse | – | 1.00x | ~0.92x | ~1.14x |
| Charm++/Recon / Charm++/Conv | 1.02x | ~0.85x | ~0.88x | ~0.63x |

**Charm++ on Reconverse beats Charm++ on old Converse** at 2, 4 and 8 PE and
ties at 1 PE. This is the robust result: it holds in both metrics, in both the
old and new data, and the 8 PE case (0.63x) is far larger than the residual
uncertainty. METG(50%) agrees — 0.0076 vs 0.0138 ms at 8 PE.

**Bare Reconverse versus bare Converse is a wash** — 0.92x to 1.14x with no
consistent sign. The apparent Converse advantage was clock-state lottery.

So the layering "inversion" was never real: what actually differed between the
two comparisons was that the bare-layer one was noise-dominated while the
Charm++-layer one was additionally corrupted by the -O2 build.

## The ULT benchmarks were affected too

`ult_bench_converse/Makefile` had the same `charmc -optimize` issue, so the
Converse ULT ports were `-O2` while the Reconverse originals were a CMake
Release `-O3` build. Rebuilding both at `-O3` improves the Converse side by
roughly 20% and shrinks Reconverse's reported advantage:

| sched_rate, 1 PE | Converse before | Converse after | Reconverse speedup before | after |
|---|---|---|---|---|
| 1 thread | 0.2943 us | 0.2368 us | 1.91x | 1.51x |
| 16 threads | 0.3184 us | 0.2400 us | 1.96x | 1.90x |
| 256 threads | 0.3253 us | 0.2425 us | 1.69x | 1.67x |

Reconverse still wins throughout — 1.5–2.1x on dispatch rate and 1.9–4.9x on the
raw context-switch primitive — but the single-thread figure in particular was
overstated. Updated numbers are in `ult_results.txt`.

## Caveats — do not over-read these

* **4 PE is the only fully trustworthy column.** All five systems land within
  +0.0% to +2.1% of the node reference there. At 8 PE, Reconverse sits +7.5%
  and Converse +0.0%, so the bare 8-PE comparison carries a systematic bias
  against Reconverse of about that size; at 2 PE the *Charm++* comparison is
  biased against Reconverse by ~6.5%.
* **Reconverse at 1 PE has no result.** All seven repetitions landed in the slow
  clock state and were discarded. That is the honest outcome, not a gap I can
  fill from this data.
* The remaining asymmetries below are real but were not eliminated.

## Two asymmetries still present

**`CMK_TRACE_ENABLED=1` in `charm_reconverse`, `=0` in `charm/mpi-linux-x86_64-smp`.**
`--with-production` normally disables tracing; it did not propagate on the
reconverse build path. Cost is a load plus a predictable branch per entry method
(`_TRACE_ONLY`, `ck-perf/trace.h:367`) — single-digit ns, so small, but it
handicaps Charm++/Reconverse, meaning the Charm++ comparison above *understates*
Reconverse. Rebuilding `charm_reconverse` with tracing off would close it.

**Reconverse calls `CcdCallBacks()` on every scheduler iteration**
(`src/scheduler.cpp:182`), and it opens with a `CmiWallTimer()` plus a heap
scan. Old Converse guards the same work behind `CsdPeriodic()`:

    #define CsdPeriodic() \
      if ((CcdNumTimerCBs() > 0) && (CpvAccess(_ccd_numchecks)-- <= 0)) CcdCallBacks();

which short-circuits on the first condition and never calls `CcdCallBacks()` at
all for a program with no timer callbacks — a bare Converse Task Bench run.
Reconverse declares `_ccd_numchecks` (`src/conv-conds.cpp:159`) but never uses
it to gate anything; the skip logic was dropped in the port. A clock call
measures ~62 ns on this hardware, so this is the right order of magnitude to
matter at fine granularity. Restoring the guard is the obvious thing to try.

**Not the cause:** `+lci_ndevices` (1, 2 and 8 devices give 5.834e-2 / 5.833e-2
/ 5.834e-2 at 1 PE — no effect). Also noted: all five binaries link
`libcuda.so.1` and `libcudart.so.12` because `craype-accel-nvidia80` and
`cudatoolkit` are loaded, and Reconverse consequently runs a spinning CUDA
driver thread (`cuda00001800007`) inside the cgroup where Converse runs its comm
thread. Unloading those modules would remove an uncontrolled spinning thread;
not done here because it changes the link line for every binary.
