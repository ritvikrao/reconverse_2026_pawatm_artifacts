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

One important limit on this filter, found the hard way: it must never be
allowed to delete *every* repetition of a system. If nothing survives, the
coarse point is not saying the node misbehaved on those runs, it is saying that
system is genuinely slower there — a result, not noise. That is exactly the
Reconverse 1 PE case (see below), which this analysis originally reported as a
blank. The analyser now rescues and flags such cells instead of dropping them.

## Results (7 repetitions, pinned, filtered)

Per-task overhead floor, us/task — median over iter = 8, 4, 2, where the kernel
contributes <0.03 us. No normalization, so this is immune to confound 3:

| system | 1 PE | 2 PE | 4 PE | 8 PE |
|---|---|---|---|---|
| MPI | 0.208 | 0.335 | 0.328 | 0.181 |
| Charm++ (old Converse) | 0.876 | 0.986 | 0.755 | 0.713 |
| Charm++ (Reconverse) | 0.811 | 0.809 | 0.637 | 0.443 |
| Converse | 0.402 | 0.611 | 0.493 | 0.300 |
| Reconverse (short-circuit) | 0.397 | 0.503 | 0.436 | 0.351 |
| Reconverse (main) | 0.434 | 0.531 | 0.469 | 0.351 |

| ratio | 1 PE | 2 PE | 4 PE | 8 PE |
|---|---|---|---|---|
| Reconverse (short-circuit) / Converse | 0.99x | 0.82x | 0.88x | 1.17x |
| Charm++/Recon / Charm++/Conv | 0.92x | 0.82x | 0.84x | 0.62x |

**Charm++ on Reconverse beats Charm++ on old Converse at every PE count**, by
8-38%. This is the robust result: it holds in both metrics and in every dataset
collected, and the 8 PE case (0.62x) is far larger than the residual
uncertainty. METG(50%) agrees — 0.0071 vs 0.0108 ms at 8 PE.

**Bare Reconverse now beats bare Converse at 2 and 4 PE** (0.82x, 0.88x), is
level at 1 PE (0.99x), and trails at 8 PE (1.17x — though Reconverse carries a
+6.6% coarse-point offset there against Converse's -0.2%, which accounts for
most of it; corrected, ~1.10x). Before the `CcdCallBacks()` short-circuit this
comparison was a wash. The earlier *apparent* Converse advantage was
clock-state lottery.

So the layering "inversion" was never real: what actually differed between the
two comparisons was that the bare-layer one was noise-dominated while the
Charm++-layer one was additionally corrupted by the -O2 build.

## Reconverse is 25% slower than every other system at 1 PE, on pure compute

At the coarsest granularity, 1 PE, the task is ~55 us of `libcore` compute and
the runtime handles one message per task — the runtime cannot matter. Across
seven repetitions of the sweep:

    mpi                73.8 74.1 55.2 55.2 74.1 55.2 73.8
    converse           74.0 55.4 55.4 73.9 74.1 55.4 74.0
    charm_old          74.6 55.8 55.7 55.7 74.3 55.7 74.4
    reconverse         74.2 69.3 69.4 74.0 69.3 69.4 73.9
    reconverse_main    69.4 69.4 69.4 73.9 74.2 74.0 69.4

Every other system reaches the node's fast state (~55) in some repetitions.
Neither Reconverse variant ever does, and both show a 69.3 value that no other
system produces — the others are cleanly bimodal at 55/74. This was originally
written off as "all repetitions landed in the slow clock state," which was
wrong: 69.3 is not the slow state, it is a third value specific to Reconverse.

A controlled test at the coarsest point (`raw/diag_1pe.log`) varied each
candidate independently, 5 repetitions each:

| configuration | median us/task |
|---|---|
| Reconverse, taskset 0-1, +setcpuaffinity | 69.4 |
| Reconverse, taskset 0-1, no affinity | 74.0 |
| Reconverse, no taskset, +setcpuaffinity | 74.0 |
| Reconverse, no taskset, no affinity | 69.4 |
| Reconverse, taskset 0-7 (wide cgroup) | 74.0 |
| Reconverse, `+lci_ndevices 1` | 73.9 |
| **Converse, taskset 0-1, +setcpuaffinity** | **55.4** |
| **Converse, no taskset, +setcpuaffinity** | **55.5** |

Pooled: Reconverse n=30, min 69.3, max 74.3 — never below 69.3 under any
configuration. Converse n=10, range 55.4-55.6, no variance at all, which
establishes that **the node was in its fast state throughout**. So this is not
clock state, and pinning, `+setcpuaffinity`, cgroup width and LCI device count
are all excluded.

It is specific to 1 PE: at 2 PE the same sweep has Reconverse at 37.33 us
against Converse's 37.48, i.e. identical. So it is not a code-generation or
data-alignment difference in the kernel, which would show at every PE count.

Notably the *per-task overhead floor* at 1 PE is unaffected — Reconverse 0.397
vs Converse 0.402 us — so whatever this is, it slows the compute inside a task
without costing message dispatch. Cause not yet identified; it is the clearest
open item in this set. Worth noting that Reconverse at 1 PE runs a spinning
CUDA driver thread where Converse runs its comm thread (see below), but the
wide-cgroup result argues against simple core contention.

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
* **Reconverse at 1 PE is 25% slower than every other system on pure compute,
  and this is real.** See the section below — it was originally written off as
  slow clock state, wrongly.
* The remaining asymmetries below are real but were not eliminated.

## The `CcdCallBacks()` short-circuit: implemented and measured

Reconverse's `CsdScheduler`/`CsdSchedulePoll` called `CcdCallBacks()` on every
trip round the loop, and it opens with a `CmiWallTimer()` (~60 ns here) plus a
heap probe — paid every iteration whether or not any timer callback exists,
which for a Task Bench run is never. Old Converse guards the same work:

    #define CsdPeriodic() \
      if ((CcdNumTimerCBs() > 0) && (CpvAccess(_ccd_numchecks)-- <= 0)) CcdCallBacks();

Reconverse had `_ccd_numchecks` but never used it to gate anything, and the
adaptive `nSkip` retuning that maintains it had been dropped along with the
`resolution` field. Both are restored on branch `ccd-shortcircuit`, in
`/u/rao1/reconverse` **and** in the separate checkout Charm++ links at
`/u/rao1/charm_reconverse/reconverse` (only the `reconverse` target needed
rebuilding — `libreconverse.so` is loaded dynamically, so Charm++ needed no
relink). Verified against `tests/conds`: the 1s/5s/10s periodic conditions and
the 7s `CcdCallFnAfter` all still fire, each with the same constant 0.149 s
offset, which is LCI/PMI startup before `CcdModuleInit`, not lag.

### Measuring it required a paired design

A before/after comparison across two sweeps cannot support this: Converse, whose
code did not change, moved by up to 12% between two consecutive sweeps, while
the effect being looked for is 5-10%. The control drifts more than the signal.

So the driver was built a second time against a `main` worktree
(`/u/rao1/reconverse_main`, task-bench build dir `reconverse/build_main`) and
carried through the sweep as a sixth system. Both variants then run at every
identical measurement point, adjacent in time, in one allocation, differing only
in that one commit — so node state, clock state and placement all cancel in the
ratio.

Per-repetition paired ratios (short-circuit / main) over the three finest
granularities, exact two-sided sign test:

| scope | n | faster | median | shift | p |
|---|---|---|---|---|---|
| 1 PE | 21 | 19 | 0.903 | −9.7% | 0.0002 |
| 2 PE | 21 | 16 | 0.907 | −9.3% | 0.027 |
| 4 PE | 21 | 16 | 0.952 | −4.8% | 0.027 |
| 8 PE | 21 | 11 | 0.946 | −5.4% | 1.000 |
| pooled | 84 | 62 | 0.911 | −8.9% | 0.00002 |

**The short-circuit is worth about 5-10% of per-task overhead at 1, 2 and 4 PE,
and is not detectable at 8 PE.** The individual ratios are noisy enough that
every range straddles 1.0 — the result rests on the consistency of the
direction (62 of 84 points faster), not on any single measurement. At 8 PE the
spread is 0.59-1.74 and the sign test is flat, so nothing is claimed there.

That the effect shrinks with PE count is what the mechanism predicts: the cost
removed is per scheduler iteration, and the ratio of scheduler iterations to
useful work is highest when few PEs are contending.

### Effect on the layer comparison

Per-task overhead floor ratios, from the same paired sweep:

| ratio | 1 PE | 2 PE | 4 PE | 8 PE |
|---|---|---|---|---|
| short-circuit / main | – | 0.95x | 0.93x | 1.00x |
| Reconverse (short-circuit) / Converse | – | 0.82x | 0.88x | 1.17x |
| Reconverse (main) / Converse | – | 0.87x | 0.95x | 1.17x |
| Charm++/Recon / Charm++/Conv | 0.92x | 0.82x | 0.84x | 0.62x |

With the short-circuit, bare Reconverse now beats bare Converse at 2 and 4 PE
(0.82x, 0.88x) rather than merely matching it. The 8 PE column still favours
Converse, but Reconverse carries a +6.6% residual coarse-point offset there
against Converse's −0.2%, which accounts for most of the 1.17x — corrected it is
~1.10x, inside the uncertainty of that column.

The Charm++-layer conclusion is unchanged and remains the most robust result in
the set: Charm++ on Reconverse is cheaper per task than Charm++ on old Converse
at every PE count, by 8-38%.

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
