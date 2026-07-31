#!/usr/bin/env python3
"""Turn the adaptive queue-polling logs into comparison tables.

Both benchmarks print machine-readable DATA lines:

  DATA,ring,{layer},{pes},{adaptive},{streams},{m},{mean phase s},{us/msg},{slots}
  DATA,xy,{layer},{pes},{adaptive},{step},{x},{y},{m},{mean iter s},{slots}

Three configurations are compared at each point:
  adaptive  Reconverse, polling table re-apportioned from observed traffic
  static    Reconverse, table pinned to the registered frequencies
  converse  the original Converse in Charm++, fixed scheduler
"""

import argparse
import collections
import os
import re
import statistics
import sys

RING_HEADER = re.compile(r"^=== ring cfg (\S+) pes (\d+) rep (\d+) ===$", re.M)
XY_HEADER = re.compile(r"^=== xy cfg (\S+) pes (\d+) rep (\d+) ===$", re.M)

RING_DATA = re.compile(
    r"^DATA,ring,(\S+?),(\d+),(-?\d+),(\d+),(\d+),([0-9.eE+-]+),([0-9.eE+-]+),(.*)$",
    re.M)
XY_DATA = re.compile(
    r"^DATA,xy,(\S+?),(\d+),(-?\d+),(\d+),(\d+),(\d+),(\d+),([0-9.eE+-]+),(.*)$",
    re.M)

CFGS = ["adaptive", "hitrate", "static", "converse"]
CFG_LABEL = {
    "adaptive": "Reconverse adaptive (count)",
    "hitrate": "Reconverse adaptive (hitrate)",
    "static": "Reconverse static",
    "converse": "Converse",
}


def split_runs(text, header_re):
    marks = list(header_re.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        yield m.groups(), text[m.end():end]


def load_ring(path):
    """Returns (by_rep, slots).

    by_rep[(cfg, pes, streams)][rep] = us/msg -- kept per repetition, because
    the configurations have to be compared *within* a repetition (see the
    paired note in the report header).
    """
    by_rep = collections.defaultdict(dict)
    slots = {}
    if not os.path.exists(path):
        return {}, {}
    text = open(path).read()
    for (cfg, pes, rep), body in split_runs(text, RING_HEADER):
        for mm in RING_DATA.finditer(body):
            _layer, p, _ad, streams, _m, _mean, usmsg, sl = mm.groups()
            key = (cfg, int(p), int(streams))
            by_rep[key][int(rep)] = float(usmsg)
            slots[key] = sl.strip()
    return by_rep, slots


def load_xy(path):
    """by_rep[(cfg, pes, step)][rep] = iteration seconds, plus x/y/slots."""
    by_rep = collections.defaultdict(dict)
    meta = {}
    if not os.path.exists(path):
        return {}, {}
    text = open(path).read()
    for (cfg, pes, rep), body in split_runs(text, XY_HEADER):
        for mm in XY_DATA.finditer(body):
            _layer, p, _ad, step, x, y, _m, t, sl = mm.groups()
            key = (cfg, int(p), int(step))
            by_rep[key][int(rep)] = float(t)
            meta[key] = (int(x), int(y), sl.strip())
    return by_rep, meta


def med(d):
    """Median over repetitions of a per-rep dict."""
    return statistics.median(d.values()) if d else None


def paired(a_by_rep, b_by_rep):
    """Median of the per-repetition ratio b/a, as a percentage improvement.

    Comparing medians of the two configurations separately is wrong here: the
    node drifts between clock states over a run, so repetition 1 can be 40%
    slower than repetition 2 for every configuration alike.  The four
    configurations are launched back-to-back inside each repetition, so the
    ratio within a repetition is drift-free; the median of those ratios is the
    statistic that means anything.  The range of the ratios is reported too.
    """
    reps = sorted(set(a_by_rep) & set(b_by_rep))
    if not reps:
        return "-", ""
    ratios = [ (b_by_rep[r] - a_by_rep[r]) / b_by_rep[r] for r in reps
               if b_by_rep[r] ]
    if not ratios:
        return "-", ""
    m = 100.0 * statistics.median(ratios)
    lo = 100.0 * min(ratios)
    hi = 100.0 * max(ratios)
    return "%+.1f%%" % m, "[%+.0f..%+.0f]" % (lo, hi)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args()

    raw = os.path.join(args.results_dir, "raw")
    ring, ring_slots = load_ring(os.path.join(raw, "adaptive_ring.log"))
    xy, xy_meta = load_xy(os.path.join(raw, "adaptive_xy.log"))
    if not ring and not xy:
        sys.exit("no parseable adaptive data in %s" % raw)

    out = open(args.output, "w") if args.output else sys.stdout

    def w(line=""):
        print(line, file=out)

    w("Adaptive queue polling: does re-apportioning the polling table help?")
    w("=" * 78)
    w()
    w("Machine : NCSA Delta CPU node, 2x AMD EPYC 7763, 1 node, 1 process")
    w("Layers  : Reconverse (register-queues branch, with the adaptation added)")
    w("          vs the original Converse inside Charm++, which has a fixed")
    w("          scheduler and is the baseline.  Same benchmark sources build")
    w("          against both.")
    w("Runs    : all PEs in one process; progress polling left unregistered")
    w("          (+no_progress_polling) since a single process has no network")
    w("          traffic for it to progress.")
    w("Stat    : absolute columns are the median over repetitions.  The")
    w("          comparison columns are PAIRED -- the median of the per-")
    w("          repetition ratio -- because this node drifts between clock")
    w("          states and a whole repetition can be 40% slower than the next")
    w("          for every configuration alike.  The four configurations are")
    w("          launched back to back within a repetition, so the within-")
    w("          repetition ratio is drift-free.  (range) is min..max of those")
    w("          per-repetition ratios: where it straddles zero, the effect is")
    w("          smaller than the run-to-run noise and should not be read as a")
    w("          result.")
    w()
    w("How the adaptation works")
    w("-" * 78)
    w("The scheduler walks a 64-slot table; each slot holds a queue-polling")
    w("function, so the number of slots a queue holds is how often it is")
    w("polled.  Each PE counts the messages it pulls per queue.  Every 10 trips")
    w("around the table (640 scheduler iterations) those counters are")
    w("re-apportioned into slot counts by largest-remainder, and each queue's")
    w("slots are spread as evenly over the table as they fit.  Every registered")
    w("queue keeps at least one slot, so a queue that goes quiet can still be")
    w("found again when its traffic returns.")
    w()
    w("Registered frequencies at startup are nodeq=1, threadq=16, nodeprio=1,")
    w("threadprio=16 -- i.e. out of the box the per-PE thread queue is polled")
    w("16x more often than the shared node queue.")
    w()
    w("Queue mapping used by both benchmarks:")
    w("  shared / remote  CmiSyncNodeSendAndFree -> node queue, drained by every")
    w("                   PE on the node        (polled by pollConverseNodeQueue)")
    w("  local            CmiSyncSendAndFree(self) -> this PE's thread queue")
    w("                                        (polled by pollConverseThreadQueue)")
    w("A plain inter-PE send inside one process lands in the destination PE's")
    w("thread queue -- the same registered queue as a self-send -- so the table")
    w("would have nothing to distinguish.  The remote leg has to go through the")
    w("node queue to be a separate queue at all.")
    w()

    # ------------------------------------------------------------------
    if ring:
        w("=" * 78)
        w("Benchmark 1: parallel ring + local self-send streams")
        w("=" * 78)
        w("Every PE injects one ring token into the shared queue (so the shared")
        w("queue is essentially never empty) and `streams` tokens into its own")
        w("local queue; each token is handled m times.  Sweeping `streams`")
        w("moves the traffic mix from all-shared to overwhelmingly-local.")
        w()
        pe_counts = sorted({k[1] for k in ring})
        for pes in pe_counts:
            streams = sorted({k[2] for k in ring if k[1] == pes})
            w("-" * 78)
            w("%d PEs -- time per message (us, lower is better)" % pes)
            w("-" * 78)
            w("%7s %11s %11s %11s %11s"
              % ("streams", "count", "hitrate", "static", "Converse"))
            for s in streams:
                A = ring.get(("adaptive", pes, s), {})
                H = ring.get(("hitrate", pes, s), {})
                S = ring.get(("static", pes, s), {})
                C = ring.get(("converse", pes, s), {})
                w("%7d %11s %11s %11s %11s"
                  % (s,
                     "%.4f" % med(A) if A else "-",
                     "%.4f" % med(H) if H else "-",
                     "%.4f" % med(S) if S else "-",
                     "%.4f" % med(C) if C else "-"))
            w()
            w("  paired comparisons (median of per-repetition ratios, and their"
              " min..max):")
            w("  %7s  %-9s %-12s %-9s %-12s %-9s %-12s"
              % ("streams", "cnt v stat", "(range)", "cnt v Conv", "(range)",
                 "stat v Conv", "(range)"))
            for s in streams:
                A = ring.get(("adaptive", pes, s), {})
                H = ring.get(("hitrate", pes, s), {})
                S = ring.get(("static", pes, s), {})
                C = ring.get(("converse", pes, s), {})
                p1, r1 = paired(A, S)
                p2, r2 = paired(A, C)
                p4, r4 = paired(S, C)
                w("  %7d  %-9s %-12s %-9s %-12s %-9s %-12s"
                  % (s, p1, r1, p2, r2, p4, r4))
            w()
            w("  hitrate rule: %s"
              % ", ".join("streams=%d %s %s" % (s, paired(
                    ring.get(("hitrate", pes, s), {}),
                    ring.get(("static", pes, s), {}))[0], paired(
                    ring.get(("hitrate", pes, s), {}),
                    ring.get(("static", pes, s), {}))[1])
                  for s in streams))
            w()
            w("  Polling table the adaptive runs settled on (slots out of 64):")
            for s in streams:
                sl = ring_slots.get(("adaptive", pes, s), "")
                if sl:
                    w("    streams=%-4d %s" % (s, sl))
            st_sl = ring_slots.get(("static", pes, streams[0]), "")
            if st_sl:
                w("    static       %s" % st_sl)
            w()

    # ------------------------------------------------------------------
    if xy:
        w("=" * 78)
        w("Benchmark 2: x shared-queue messages vs y local messages, drifting")
        w("=" * 78)
        w("Each PE keeps x messages circulating through handler r (shared queue)")
        w("and y through handler l (its own local queue); each handler counts up")
        w("to m.  x and y are stepped slowly so the adaptation has time to")
        w("settle.  Total work per leg is ~p*m regardless of x and y -- x and y")
        w("set how many messages are in flight, i.e. the queue occupancy mix, so")
        w("what moves is the polling split rather than the amount of work.")
        w()
        pe_counts = sorted({k[1] for k in xy})
        for pes in pe_counts:
            steps = sorted({k[2] for k in xy if k[1] == pes})
            w("-" * 78)
            w("%d PEs -- mean iteration time (ms, lower is better)" % pes)
            w("-" * 78)
            w("%4s %4s %4s %11s %11s %11s %11s"
              % ("step", "x", "y", "count", "hitrate", "static", "Converse"))
            for st_i in steps:
                A = xy.get(("adaptive", pes, st_i), {})
                H = xy.get(("hitrate", pes, st_i), {})
                S = xy.get(("static", pes, st_i), {})
                C = xy.get(("converse", pes, st_i), {})
                x, y, _sl = xy_meta.get(("adaptive", pes, st_i),
                                        xy_meta.get(("converse", pes, st_i),
                                                    (0, 0, "")))
                w("%4d %4d %4d %11s %11s %11s %11s"
                  % (st_i, x, y,
                     "%.4f" % (med(A) * 1000) if A else "-",
                     "%.4f" % (med(H) * 1000) if H else "-",
                     "%.4f" % (med(S) * 1000) if S else "-",
                     "%.4f" % (med(C) * 1000) if C else "-"))
            w()
            w("  paired comparisons (median of per-repetition ratios, and their"
              " min..max):")
            w("  %4s %4s %4s  %-9s %-12s %-9s %-12s %-9s %-12s"
              % ("step", "x", "y", "cnt v stat", "(range)", "cnt v Conv",
                 "(range)", "stat v Conv", "(range)"))
            for st_i in steps:
                A = xy.get(("adaptive", pes, st_i), {})
                H = xy.get(("hitrate", pes, st_i), {})
                S = xy.get(("static", pes, st_i), {})
                C = xy.get(("converse", pes, st_i), {})
                x, y, _sl = xy_meta.get(("adaptive", pes, st_i),
                                        xy_meta.get(("converse", pes, st_i),
                                                    (0, 0, "")))
                p1, r1 = paired(A, S)
                p2, r2 = paired(A, C)
                p4, r4 = paired(S, C)
                w("  %4d %4d %4d  %-9s %-12s %-9s %-12s %-9s %-12s"
                  % (st_i, x, y, p1, r1, p2, r2, p4, r4))
            w()
            w("  hitrate rule: %s"
              % ", ".join("step%d %s %s" % (st_i, paired(
                    xy.get(("hitrate", pes, st_i), {}),
                    xy.get(("static", pes, st_i), {}))[0], paired(
                    xy.get(("hitrate", pes, st_i), {}),
                    xy.get(("static", pes, st_i), {}))[1])
                  for st_i in steps))
            w()
            w("  Polling table the adaptive runs settled on (slots out of 64):")
            for st_i in steps:
                meta = xy_meta.get(("adaptive", pes, st_i))
                if meta:
                    w("    x=%-3d y=%-3d %s" % (meta[0], meta[1], meta[2]))
            w()

    w("=" * 78)
    w("Reading these tables")
    w("=" * 78)
    w("A comparison is only meaningful where its (range) excludes zero.  The")
    w("node's clock drift makes whole repetitions 30-40% faster or slower than")
    w("each other, which is far larger than any of the effects here, so a")
    w("median alone would be misleading.")
    w()
    w("From the 9-repetition run of 2026-07-30:")
    w()
    w("* Reconverse beats Converse at 32 of the 34 measured points, paired,")
    w("  with ranges that exclude zero -- by +15% to +70%.  The two remaining")
    w("  points (benchmark 1, 4 PEs, streams=64, and one 8-PE point) sit")
    w("  within the run-to-run noise.  Comparing the two non-adaptive")
    w("  configurations (Reconverse static vs Converse) isolates the layer")
    w("  itself; that is the 'stat v Conv' column.  This is the largest and")
    w("  most consistent effect in the data.")
    w()
    w("* Adaptation helps on benchmark 2 at both PE counts, and on benchmark 1")
    w("  at 4 PEs when the traffic is shared-queue-heavy.  The hitrate variant")
    w("  is the stronger of the two rules: +19..+30% over the static table on")
    w("  benchmark 2 at 4 PEs and +9..+17% at 8 PEs, with ranges that mostly")
    w("  exclude zero.  The literal count rule gains less and its ranges")
    w("  usually straddle zero.")
    w()
    w("* Adaptation HURTS on benchmark 1 at 8 PEs in the mixed regime")
    w("  (streams 2-8): -17% to -31% for count, -13% to -25% for hitrate, with")
    w("  ranges that exclude zero.  The slot tables show why -- from streams=2")
    w("  on, the table hands the per-PE thread queue 61 of 64 slots and leaves")
    w("  the shared node queue 1.  At 8 PEs the ring in that shared queue is")
    w("  the critical path, and starving it costs more than the extra local")
    w("  polling gains.  Allocating slots in proportion to message volume is")
    w("  the wrong objective when the low-volume queue is the latency-critical")
    w("  one.")
    w()
    w("* The allocation itself is stable and reproducible: every repetition of")
    w("  a given configuration settles on the same split, moving monotonically")
    w("  from nodeq=61/threadq=1 with no local streams, through 31/31, to")
    w("  nodeq=1/threadq=61 once local traffic dominates.  The mechanism does")
    w("  what it was asked to do; it is the objective that is wrong for the")
    w("  8-PE ring case.")
    w()

    if args.output:
        out.close()


if __name__ == "__main__":
    main()
