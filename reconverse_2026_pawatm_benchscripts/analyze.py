#!/usr/bin/env python3
"""Turn the raw task-bench sweep logs into the granularity/efficiency table.

Follows the upstream task-bench analysis (scripts/chart_metg.py):

    time_per_task (ms) = elapsed / total_tasks * nodes * cores * 1000
    efficiency         = (total_FLOPs / elapsed / nodes) / peak_FLOP/s

`cores` and the peak used for a given point are those of the PE count that
point was run at, so 1-, 2-, 4- and 8-PE curves are each measured against
what that many cores can actually do.

Peak FLOP/s per core count comes from task-bench's own kernel_bench, which
runs the same compute_bound kernel in a bare pinned-pthread loop with no
runtime underneath.
"""

import argparse
import collections
import os
import re
import statistics
import sys

RUN_HEADER = re.compile(
    r"^=== system (\S+) pes (\d+) iter (\d+) rep (\d+) ===$", re.MULTILINE
)
PEAK_HEADER = re.compile(r"^=== peak pes (\d+) rep (\d+) ===$", re.MULTILINE)

FIELDS = {
    "elapsed": (re.compile(r"^\s*Elapsed Time ([0-9.e+-]+) seconds$", re.M), float),
    "flops": (re.compile(r"^\s*Total FLOPs ([0-9]+)$", re.M), int),
    "tasks": (re.compile(r"^\s*Total Tasks ([0-9]+)$", re.M), int),
    "iterations": (re.compile(r"^\s*Iterations: ([0-9]+)$", re.M), int),
    "width": (re.compile(r"^\s*Max Width: ([0-9]+)$", re.M), int),
    "steps": (re.compile(r"^\s*Time Steps: ([0-9]+)$", re.M), int),
}

SYSTEM_LABEL = collections.OrderedDict(
    [
        ("mpi", "MPI"),
        ("charm_old", "Charm++ (old Converse)"),
        ("charm_reconv", "Charm++ (Reconverse)"),
        ("converse", "Converse"),
        ("reconverse", "Reconverse (short-circuit)"),
        ("reconverse_main", "Reconverse (main)"),
    ]
)

THRESHOLD = 0.5  # METG(50%)


def split_runs(text, header_re):
    """Yield (header_groups, body) for each '=== ... ===' delimited block."""
    marks = list(header_re.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        yield m.groups(), text[m.end() : end]


def parse_body(body):
    out = {}
    for key, (pat, conv) in FIELDS.items():
        found = pat.findall(body)
        if not found:
            return None
        out[key] = conv(found[-1])
    return out


def load_peak(path):
    """Per core count: (best, mean, spread%, n) FLOP/s over the repetitions.

    These nodes show ~20-25% run-to-run variation from CPU boost residency at
    low core counts, so a single measurement is not a usable denominator; the
    spread is reported so the reader can see it.
    """
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        text = f.read()
    peak = collections.defaultdict(list)
    for (pes, _rep), body in split_runs(text, PEAK_HEADER):
        d = parse_body(body)
        if d and d["elapsed"] > 0:
            peak[int(pes)].append(d["flops"] / d["elapsed"])
    out = {}
    for p, v in peak.items():
        if v:
            out[p] = (max(v), statistics.mean(v), 100.0 * (max(v) - min(v)) / max(v),
                      len(v))
    return out


def load_runs(raw_dir):
    """(system, pes, iter) -> list of per-rep dicts."""
    runs = collections.defaultdict(list)
    for name in sorted(os.listdir(raw_dir)):
        if not name.endswith(".log") or name.startswith("kernel_bench"):
            continue
        with open(os.path.join(raw_dir, name)) as f:
            text = f.read()
        for (sys_, pes, it, rep), body in split_runs(text, RUN_HEADER):
            d = parse_body(body)
            if d is None or d["elapsed"] <= 0:
                continue
            d["rep"] = int(rep)
            runs[(sys_, int(pes), int(it))].append(d)
    return runs


def fast_state_reference(runs, coarsest):
    """pes -> per-task cost at the coarsest granularity with the node healthy.

    Taken as the 25th percentile over every system and repetition, which is
    robust both to a rare boost state at the bottom and to a majority of
    contaminated runs at the top.  This doubles as the shared denominator for
    the efficiency curve, so that no system is rewarded for having happened to
    measure its own reference point in a slow clock state.
    """
    ref = {}
    for pes, coarse_it in coarsest.items():
        vals = []
        for (sys_, p, it), reps in runs.items():
            if p == pes and it == coarse_it:
                vals.extend(r["elapsed"] / r["tasks"] for r in reps)
        if vals:
            vals.sort()
            ref[pes] = vals[max(0, int(0.25 * (len(vals) - 1)))]
    return ref


def drop_slow_clock_reps(runs, coarsest, tol=0.10):
    """Discard whole repetitions that ran in the node's slow clock state.

    These nodes sit in one of two sustained clock states about 30% apart, and
    which one a run catches is not controlled by the benchmark.  The coarsest
    granularity point is a pure-compute control: a task there is ~55 us of
    libcore work and the runtime handles one message per task, so every system
    must agree on it.  Within a single repetition all systems run adjacent in
    time, so the fastest coarse point in that repetition is the fast state.

    Any (system, PE count, repetition) whose coarse point sits more than `tol`
    above that repetition's best is a run that fell into the slow state, and
    every granularity it measured is inflated by the same factor -- so the
    whole repetition is dropped for that system, not just its coarse point.
    Dropping only the coarse point would be worse than useless: it would leave
    the inflated fine points in while removing the evidence they were inflated.
    """
    # The fast clock state belongs to the node, not to a repetition, so the
    # reference has to be global.  A within-repetition reference fails exactly
    # when it matters most: if every system ran slow in some repetition, that
    # repetition has no fast member and survives untouched.
    #
    # But the global *minimum* is not usable either -- these nodes have at
    # least three clock states, and the fastest is rare.  At 4 PE the four
    # quickest coarse runs (14.2-14.5 us) belong to Converse and Charm++/old-
    # Converse alone, against a main cluster at 17.4-18.9; keying off the
    # minimum would have discarded 30 of 34 runs.  The 25th percentile is a
    # robust stand-in for "the node running normally" that neither a rare boost
    # state nor a contaminated majority can drag around.
    ref = fast_state_reference(runs, coarsest)

    slow = set()  # (system, pes, rep) to discard
    for (sys_, pes, it), reps in runs.items():
        if it != coarsest.get(pes):
            continue
        for r in reps:
            base = ref.get(pes)
            if base and r["elapsed"] / r["tasks"] > base * (1.0 + tol):
                slow.add((sys_, pes, r["rep"]))

    # A filter that can delete every repetition of a system is not filtering,
    # it is concluding -- and concluding the wrong thing.  If NO repetition of
    # some (system, PE count) survives, the coarse point is not telling us the
    # node misbehaved on those runs; it is telling us that system is
    # consistently slower there, which is a result and not noise.  Reconverse
    # at 1 PE is exactly this case: 30 runs across six configurations never got
    # below 69.3 us while Converse held 55.4-55.6 on the same node, so pinning,
    # +setcpuaffinity, cgroup width and LCI device count are all excluded.
    # Keep those repetitions and flag them loudly instead of reporting a blank.
    rescued = set()
    for sys_, pes, _it in list(runs):
        if (sys_, pes) in rescued:
            continue
        reps_here = {r["rep"] for k, v in runs.items()
                     if k[0] == sys_ and k[1] == pes for r in v}
        if reps_here and all((sys_, pes, rp) in slow for rp in reps_here):
            rescued.add((sys_, pes))
    slow = {(s, p, r) for (s, p, r) in slow if (s, p) not in rescued}

    dropped = 0
    for key in list(runs):
        sys_, pes, _it = key
        keep = [r for r in runs[key] if (sys_, pes, r["rep"]) not in slow]
        dropped += len(runs[key]) - len(keep)
        if keep:
            runs[key] = keep
        else:
            del runs[key]
    return runs, slow, dropped, rescued


def metg(points):
    """Smallest task granularity still at or above the efficiency threshold.

    Interpolates between the last point above and the first below, as
    chart_metg.py does.  points must be sorted by decreasing granularity.
    """
    above = [p for p in points if p["efficiency"] >= THRESHOLD]
    if not above:
        return None, "no point reached the %d%% threshold" % (THRESHOLD * 100)
    best = min(above, key=lambda p: p["time_per_task"])
    i = points.index(best)
    if i + 1 >= len(points):
        return best["time_per_task"], "threshold not crossed within the sweep"
    nxt = points[i + 1]
    if nxt["time_per_task"] >= best["time_per_task"]:
        return best["time_per_task"], ""
    # linear interpolation in (efficiency, granularity)
    span = best["efficiency"] - nxt["efficiency"]
    if span <= 0:
        return best["time_per_task"], ""
    frac = (best["efficiency"] - THRESHOLD) / span
    return (
        best["time_per_task"] + frac * (nxt["time_per_task"] - best["time_per_task"]),
        "",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--clock-tol", type=float, default=0.10,
                    help="coarse-point excess over the best system in the same "
                         "repetition above which that repetition is treated as "
                         "having run in the node's slow clock state")
    ap.add_argument("--keep-slow", action="store_true",
                    help="do not discard slow-clock-state repetitions")
    args = ap.parse_args()

    raw = os.path.join(args.results_dir, "raw")
    kb = load_peak(os.path.join(raw, "kernel_bench_peak.log"))
    runs = load_runs(raw)
    if not runs:
        sys.exit("no parseable runs in %s" % raw)

    # Hardware peak, used only for the secondary "vs peak" column.
    peak = {p: v[0] for p, v in kb.items()}

    # The coarsest granularity run for each (system, PE count).  This is the
    # per-system reference point for the primary efficiency definition below:
    # at 55-75 ms per task the runtime's own overhead is microseconds, so it
    # represents that system running with no meaningful overhead.
    coarsest = {}
    for (_sys, pes, it) in runs:
        coarsest[pes] = max(coarsest.get(pes, 0), it)

    n_before = sum(len(v) for v in runs.values())
    if args.keep_slow:
        slow, dropped, rescued = set(), 0, set()
    else:
        runs, slow, dropped, rescued = drop_slow_clock_reps(
            runs, coarsest, args.clock_tol)
    clock_ref = fast_state_reference(runs, coarsest)
    clock_ref0 = clock_ref

    out = open(args.output, "w") if args.output else sys.stdout

    def w(line=""):
        print(line, file=out)

    w("Task Bench: minimum effective task granularity (METG)")
    w("=" * 78)
    w()
    w("Machine      : NCSA Delta CPU node, 2x AMD EPYC 7763 (64 cores each), 1 node")
    w("Dependence   : stencil_1d")
    w("Kernel       : compute_bound")
    w("Time steps   : 1000")
    w("Graph width  : equal to the PE count")
    w("Granularity  : swept with -iter, halving from 16384 down to 2")
    w("PE placement : MPI uses one rank per PE; Charm++, Converse and Reconverse")
    w("               put all PEs in a single process")
    w()
    w("time_per_task = elapsed / total_tasks * cores * 1000   [ms]")
    w()
    w("efficiency (the METG curve) is measured against each system's OWN")
    w("coarsest-granularity run, as task-bench's chart_metg.py does when no")
    w("hardware peak is supplied:")
    w()
    w("    scale_factor = iter_coarsest / iter")
    w("    efficiency   = elapsed_coarsest / (elapsed * scale_factor)")
    w()
    w("At the coarsest point a task is 55-75 ms and the runtime's own overhead")
    w("is microseconds, so that point is that system running essentially")
    w("overhead-free.  Normalising there isolates what METG is meant to")
    w("measure -- how small a task the runtime can still keep cores busy on --")
    w("and cancels the node's clock-state variation, which moves a system's")
    w("coarse and fine points together.")
    w()
    w("'vs peak' is the secondary, absolute view: achieved FLOP/s over the")
    w("kernel_bench hardware peak for that core count.  It can exceed 100%")
    w("when a run catches the boosted clock state that kernel_bench, which")
    w("pins worker i to core i, does not reach on cores 1..n-1.")
    w()
    w("Hardware peak per core count (task-bench kernel_bench: the same kernel in")
    w("a bare pinned-pthread loop, no runtime underneath), used for 'vs peak':")
    w()
    w("%6s %16s %12s %8s" % ("cores", "peak FLOP/s", "spread", "reps"))
    for p in sorted(kb):
        w("%6d %16.6e %11.1f%% %8d" % (p, kb[p][0], kb[p][2], kb[p][3]))
    w()
    w("Statistic: every point below is the MEDIAN of %d repetitions."
      % max((len(v) for v in runs.values()), default=0))
    w()
    w("These nodes intermittently drop to a lower sustained clock, costing")
    w("about 25-33% on identical work; the effect is bimodal rather than")
    w("gaussian, so a mean is pulled around by however many slow repetitions a")
    w("configuration happened to catch, and a best-of rewards whichever system")
    w("got lucky.  The median rejects up to two contaminated repetitions out")
    w("of five.  The 'spread' column is (worst-best)/best, so it shows how")
    w("much each point was affected.")
    w()
    w("The sweep itself interleaves all five systems at every measurement point")
    w("and rotates which one goes first on each repetition.  Running each")
    w("system's sweep as a contiguous block -- as done initially -- gave")
    w("whichever system ran first a systematically cooler node and biased the")
    w("comparison by ~25%.")
    w()
    w("Every system is pinned to the same contiguous core range (cores 0..P,")
    w("one CCX of one socket at these PE counts).  Leaving placement to slurm")
    w("and each runtime's +setcpuaffinity made the result depend on the shape")
    w("of the enclosing allocation: the identical sweep rerun under a different")
    w("allocation shape moved fine-granularity overhead by 4x while leaving the")
    w("compute-bound coarse point unchanged.")
    w()
    if args.keep_slow:
        w("Slow-clock-state filtering: DISABLED (--keep-slow).")
    else:
        w("Slow-clock-state filter: a repetition whose coarsest-granularity")
        w("point -- ~55 us of pure compute, one message per task, so every")
        w("system must agree on it -- came in more than %.0f%% above the fastest"
          % (args.clock_tol * 100))
        w("coarse point seen at that PE count is taken to have run in the")
        w("node's slow clock state, and that repetition is discarded for that")
        w("system at every granularity, since all of them are inflated")
        w("together.  The reference is global rather than within-repetition:")
        w("the fast state belongs to the node, and a within-repetition")
        w("reference cannot detect a repetition in which every system ran slow.")
        w()
        w("Discarded %d of %d runs (%.1f%%)%s"
          % (dropped, n_before, 100.0 * dropped / max(n_before, 1),
             ":" if slow else "; none were affected."))
        if slow:
            by_sys = collections.Counter(s for (s, _p, _r) in slow)
            for s, n in sorted(by_sys.items(), key=lambda kv: -kv[1]):
                w("    %-24s %d (system, PE-count, repetition) combinations"
                  % (SYSTEM_LABEL.get(s, s), n))
        if rescued:
            w()
            w("NOT filtered, despite exceeding the tolerance in every")
            w("repetition -- a system that is never once within tolerance is")
            w("not a system that met bad luck, it is a system that is really")
            w("slower there, and discarding it would report a blank in place")
            w("of a result:")
            for s, p in sorted(rescued, key=lambda x: (x[0], x[1])):
                base = clock_ref0.get(p)
                key = (s, p, coarsest[p])
                if base and key in runs:
                    med = statistics.median(r["elapsed"] for r in runs[key])
                    pt = med / runs[key][0]["tasks"]
                    w("    %-26s %d PE: coarse point %.1f us/task, %+.0f%% vs "
                      "the node reference" % (SYSTEM_LABEL.get(s, s), p,
                                              pt * 1e6, (pt / base - 1) * 100))
            w("    Their whole efficiency curve is scaled by that factor, so")
            w("    METG and 'efficiency' for these rows are NOT comparable")
            w("    with the others; the overhead floor below still is.")
    w()

    systems = [s for s in SYSTEM_LABEL if any(k[0] == s for k in runs)]
    systems += sorted({k[0] for k in runs} - set(SYSTEM_LABEL))
    pe_counts = sorted({k[1] for k in runs})

    summary = []

    for sys_ in systems:
        label = SYSTEM_LABEL.get(sys_, sys_)
        for pes in pe_counts:
            iters = sorted({k[2] for k in runs if k[0] == sys_ and k[1] == pes},
                           reverse=True)
            if not iters:
                continue
            w("-" * 78)
            w("%s -- %d PE(s)" % (label, pes))
            w("-" * 78)
            # Shared denominator: the node's healthy coarse-point cost per
            # task at this PE count, identical for every system.  Normalising
            # each system against its OWN coarsest run -- the obvious choice,
            # and what this script did originally -- makes METG a lottery,
            # because that one run is the measurement most exposed to the
            # node's clock state and a system that happened to measure its
            # reference slow is scored generously ever after.
            ref_iter = float(coarsest[pes])
            ref_per_task = clock_ref.get(pes)
            if ref_per_task is None:
                continue

            w("%9s %5s %14s %7s %14s %16s %10s %9s"
              % ("iter", "reps", "elapsed(s)", "spread", "granularity",
                 "FLOP/s", "efficiency", "vs peak"))
            w("%9s %5s %14s %7s %14s %16s %10s %9s"
              % ("", "", "median", "(%)", "(ms/task)", "", "(%)", "(%)"))
            points = []
            for it in iters:
                reps = runs[(sys_, pes, it)]
                elapsed = [r["elapsed"] for r in reps]
                med = statistics.median(elapsed)
                spread = 100.0 * (max(elapsed) - min(elapsed)) / min(elapsed)
                tasks = reps[0]["tasks"]
                flops = reps[0]["flops"]
                gran = med / tasks * pes * 1000.0
                fps = flops / med
                # Primary: how much of the node's overhead-free rate this
                # system still delivers once tasks shrink.  scale_factor is how
                # much less compute this point does than the reference point.
                scale_factor = ref_iter / float(it)
                eff = (ref_per_task * tasks) / (med * scale_factor)
                eff_hw = fps / peak[pes] if pes in peak else None
                points.append(
                    {
                        "iter": it,
                        "reps": len(reps),
                        "elapsed": med,
                        "time_per_task": gran,
                        "flops_per_second": fps,
                        "efficiency": eff,
                    }
                )
                w("%9d %5d %14.6e %7.1f %14.6e %16.6e %10.2f %9s"
                  % (it, len(reps), med, spread, gran, fps, eff * 100,
                     ("%.1f" % (eff_hw * 100)) if eff_hw is not None else "n/a"))
            if pes in peak:
                value, note = metg(points)
                if value is None:
                    w()
                    w("METG(50%%): not determined -- %s" % note)
                else:
                    w()
                    w("METG(50%%): %.6e ms/task%s"
                      % (value, ("   [%s]" % note) if note else ""))
                    summary.append((label, pes, value, note))
            w()

    w("=" * 78)
    w("Summary: METG(50%) in ms per task")
    w("=" * 78)
    w("%-26s %s" % ("system", "".join("%14s" % ("%d PE" % p) for p in pe_counts)))
    for label in [SYSTEM_LABEL.get(s, s) for s in systems]:
        row = ""
        for p in pe_counts:
            hit = [v for (l, pp, v, _n) in summary if l == label and pp == p]
            row += "%14s" % (("%.4f" % hit[0]) if hit else "-")
        w("%-26s %s" % (label, row))
    w()
    w("Lower METG is better: it is the smallest average task duration at which")
    w("the system still delivers 50% of the achievable FLOP rate.")
    w()

    # ---------------------------------------------------------------------
    # METG(50%) is self-normalised against each system's own coarsest point,
    # which makes it sensitive to anything that perturbs that one point --
    # and the coarsest point is 55 ms of pure compute, so a placement or
    # clock difference there moves METG without any scheduler being involved.
    # The two statistics below use no normalisation at all.
    # ---------------------------------------------------------------------
    w("=" * 78)
    w("Cross-check 1: coarsest-granularity cost (us per task, iter=%s)"
      % max(coarsest.values()))
    w("=" * 78)
    w("At the coarsest point a task is ~55 us of libcore compute and the")
    w("runtime handles one message per task, so every system should land on")
    w("the same number.  Where one does not, the difference is placement or")
    w("clock state, NOT runtime overhead -- and it propagates into that")
    w("system's METG through the normalisation.")
    w()
    w("Shown as us/task and, in brackets, the excess over the shared node")
    w("reference for that PE count.  Anything more than a couple of percent is")
    w("residual clock/placement offset that the filter's tolerance let through,")
    w("and it biases that system's whole efficiency curve by the same factor --")
    w("so a curve sitting uniformly low is not evidence of runtime overhead")
    w("unless its bracket is near zero.")
    w()
    w("%-26s %s" % ("system", "".join("%18s" % ("%d PE" % p) for p in pe_counts)))
    for sys_ in systems:
        label = SYSTEM_LABEL.get(sys_, sys_)
        row = ""
        for p in pe_counts:
            key = (sys_, p, coarsest[p])
            if key in runs:
                med = statistics.median(r["elapsed"] for r in runs[key])
                per_task = med / runs[key][0]["tasks"] * 1e6
                base = clock_ref.get(p)
                excess = (per_task / (base * 1e6) - 1.0) * 100 if base else 0.0
                row += "%11.3f[%+4.1f%%]" % (per_task, excess)
            else:
                row += "%18s" % "-"
        w("%-26s %s" % (label, row))
    w()

    w("=" * 78)
    w("Cross-check 2: per-task overhead floor (us per task)")
    w("=" * 78)
    w("Median of elapsed/tasks over the three finest granularities")
    w("(iter = 8, 4, 2), where the kernel contributes under 0.03 us and what")
    w("is left is the runtime's own per-task cost.  No normalisation, so this")
    w("is immune to the coarse-point artefact above.")
    w()
    w("%-26s %s" % ("system", "".join("%14s" % ("%d PE" % p) for p in pe_counts)))
    floors = {}
    for sys_ in systems:
        label = SYSTEM_LABEL.get(sys_, sys_)
        row = ""
        for p in pe_counts:
            vals = []
            for it in (8, 4, 2):
                key = (sys_, p, it)
                if key in runs:
                    med = statistics.median(r["elapsed"] for r in runs[key])
                    vals.append(med / runs[key][0]["tasks"] * 1e6)
            if vals:
                floors[(sys_, p)] = statistics.median(vals)
                row += "%14.3f" % floors[(sys_, p)]
            else:
                row += "%14s" % "-"
        w("%-26s %s" % (label, row))
    w()
    w("The two comparisons the layering question turns on:")
    w()
    w("%-26s %s" % ("ratio", "".join("%14s" % ("%d PE" % p) for p in pe_counts)))
    for a, b, name in (("reconverse", "reconverse_main",
                        "short-circuit / main"),
                       ("reconverse", "converse", "Reconverse / Converse"),
                       ("reconverse_main", "converse", "Recon(main) / Converse"),
                       ("charm_reconv", "charm_old", "Ch++Recon / Ch++Conv")):
        row = ""
        for p in pe_counts:
            if (a, p) in floors and (b, p) in floors and floors[(b, p)]:
                row += "%13.2fx" % (floors[(a, p)] / floors[(b, p)])
            else:
                row += "%14s" % "-"
        w("%-26s %s" % (name, row))
    w()
    w("Below 1.00x means the Reconverse-based system is cheaper per task.")

    if args.output:
        out.close()


if __name__ == "__main__":
    main()
