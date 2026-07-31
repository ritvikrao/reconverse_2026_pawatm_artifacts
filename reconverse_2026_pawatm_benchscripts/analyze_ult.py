#!/usr/bin/env python3
"""Turn the raw ULT benchmark logs into a comparison table.

Both benchmarks print machine-readable DATA lines:

  DATA,sched_rate,{pe},{threads},{yields},{best us/dispatch},{mean us/dispatch},{best M dispatch/s}
  DATA,ctxswitch,{pe},{flows},{direct us/switch},{scheduler us/switch}

The same source builds against Reconverse and against the original Converse in
Charm++, so the two layers run identical benchmark code.
"""

import argparse
import collections
import os
import re
import sys

SCHED_HEADER = re.compile(
    r"^=== ult sched_rate layer (\S+) pes (\d+) threads (\d+) ===$", re.M
)
CTX_HEADER = re.compile(r"^=== ult ctxswitch layer (\S+) pes (\d+) ===$", re.M)

SCHED_DATA = re.compile(
    r"^DATA,sched_rate,(\d+),(\d+),(\d+),([0-9.eE+-]+),([0-9.eE+-]+),([0-9.eE+-]+)$",
    re.M,
)
CTX_DATA = re.compile(
    r"^DATA,ctxswitch,(\d+),(\d+),([0-9.eE+-]+),([0-9.eE+-]+)$", re.M
)

LAYERS = ["reconverse", "converse"]
LAYER_LABEL = {"reconverse": "Reconverse", "converse": "Converse (Charm++)"}


def split_runs(text, header_re):
    marks = list(header_re.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        yield m.groups(), text[m.end() : end]


def load_sched(path):
    """(layer, pes, threads) -> (us/dispatch, spread, n_pes).

    Each PE independently reports its own best-of-reps figure.  PEs run
    identical, independent work, so the mean across them is the representative
    number; the min would be both optimistic and noisy.  `spread` is the
    max-min across PEs, to show how much the PEs disagreed.
    """
    table = {}
    if not os.path.exists(path):
        return table
    with open(path) as f:
        text = f.read()
    for (layer, pes, threads), body in split_runs(text, SCHED_HEADER):
        rows = SCHED_DATA.findall(body)
        if not rows:
            continue
        per_pe = [float(r[3]) for r in rows]
        mean = sum(per_pe) / len(per_pe)
        table[(layer, int(pes), int(threads))] = (
            mean,
            max(per_pe) - min(per_pe),
            len(per_pe),
        )
    return table


def load_ctx(path):
    """(layer, pes, flows) -> (direct us/switch, scheduler us/switch, n_pes).

    As with sched_rate, each PE reports its own best-of-reps figure and the
    mean across PEs is the representative number.
    """
    table = {}
    if not os.path.exists(path):
        return table
    with open(path) as f:
        text = f.read()
    for (layer, pes), body in split_runs(text, CTX_HEADER):
        per_flow = collections.defaultdict(list)
        for _pe, flows, direct, sched in CTX_DATA.findall(body):
            per_flow[int(flows)].append((float(direct), float(sched)))
        for flows, vals in per_flow.items():
            table[(layer, int(pes), flows)] = (
                sum(v[0] for v in vals) / len(vals),
                sum(v[1] for v in vals) / len(vals),
                len(vals),
            )
    return table


def ratio(a, b):
    if a is None or b is None or b == 0:
        return "-"
    return "%.2fx" % (a / b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args()

    raw = os.path.join(args.results_dir, "raw")
    sched = load_sched(os.path.join(raw, "ult_sched_rate.log"))
    ctx = load_ctx(os.path.join(raw, "ult_ctxswitch.log"))
    if not sched and not ctx:
        sys.exit("no parseable ULT data in %s" % raw)

    out = open(args.output, "w") if args.output else sys.stdout

    def w(line=""):
        print(line, file=out)

    w("User-level thread (ULT) benchmarks: Reconverse vs original Converse")
    w("=" * 78)
    w()
    w("Machine : NCSA Delta CPU node, 2x AMD EPYC 7763 (64 cores each), 1 node")
    w("Source  : reconverse/tests/ult_bench (sched_rate.cpp, ctxswitch.cpp).")
    w("          The same sources build against both layers; the Converse build")
    w("          differs only in ConverseInit's argument count (see")
    w("          /u/rao1/ult_bench_converse/converse_compat.h), so the measured")
    w("          code paths are identical.")
    w("Threads : Converse uses the Charm++ build's default ULT implementation")
    w("          (generic64-light assembly threads); Reconverse uses its")
    w("          boost-context based threads.")
    w("Numbers : each PE reports its own best-of-repetitions figure; the tables")
    w("          show the mean across PEs.  Lower is better throughout.")
    w()
    w("Caveat  : in the sched_rate sweep both layers speed up at the largest")
    w("          thread counts (>=512).  That is a property of the benchmark --")
    w("          more runnable ULTs amortise the fixed per-repetition costs --")
    w("          not of either runtime, and it shows up equally in both, so the")
    w("          Converse/Reconverse ratio is the meaningful column.")
    w()

    # ------------------------------------------------------------------
    if sched:
        pe_counts = sorted({k[1] for k in sched})
        for pes in pe_counts:
            threads = sorted({k[2] for k in sched if k[1] == pes})
            w("-" * 78)
            w("Scheduling (dispatch) rate -- %d PE(s)" % pes)
            w("-" * 78)
            w("A dispatch is one trip through the ready path: CthAwaken pushes the")
            w("thread's token, CsdScheduler pops it, the thread resumes.  -threads")
            w("sets how many ULTs are runnable at once (ready-queue depth).")
            w()
            w("%8s %14s %14s %14s %14s %10s"
              % ("threads", "Reconverse", "Converse", "Reconverse", "Converse",
                 "speedup"))
            w("%8s %14s %14s %14s %14s %10s"
              % ("", "us/dispatch", "us/dispatch", "M disp/s", "M disp/s",
                 "(conv/recv)"))
            for t in threads:
                r = sched.get(("reconverse", pes, t))
                c = sched.get(("converse", pes, t))
                rb = r[0] if r else None
                cb = c[0] if c else None
                w("%8d %14s %14s %14s %14s %10s"
                  % (t,
                     "%.4f" % rb if rb else "-",
                     "%.4f" % cb if cb else "-",
                     "%.3f" % (1.0 / rb) if rb else "-",
                     "%.3f" % (1.0 / cb) if cb else "-",
                     ratio(cb, rb)))
            w()

    # ------------------------------------------------------------------
    if ctx:
        pe_counts = sorted({k[1] for k in ctx})
        for pes in pe_counts:
            flows = sorted({k[2] for k in ctx if k[1] == pes})
            w("-" * 78)
            w("ULT-to-ULT context switch cost vs concurrent flows -- %d PE(s)" % pes)
            w("-" * 78)
            w("direct    : flows wired into a ring, each hands off with CthResume")
            w("            (one swapcontext, no queue) -- the switch primitive alone.")
            w("scheduler : the same flows hand off with CthYield -- two swapcontexts")
            w("            plus a ready-queue push/pop and a handler dispatch.")
            w("Total switches per repetition is held fixed as flows varies, so only")
            w("the stack working set changes across a row.")
            w()
            w("%8s %13s %13s %10s %13s %13s %10s"
              % ("flows", "Reconverse", "Converse", "speedup",
                 "Reconverse", "Converse", "speedup"))
            w("%8s %13s %13s %10s %13s %13s %10s"
              % ("", "direct us", "direct us", "(conv/recv)",
                 "sched us", "sched us", "(conv/recv)"))
            for f in flows:
                r = ctx.get(("reconverse", pes, f))
                c = ctx.get(("converse", pes, f))
                rd, rs = (r[0], r[1]) if r else (None, None)
                cd, cs = (c[0], c[1]) if c else (None, None)
                w("%8d %13s %13s %10s %13s %13s %10s"
                  % (f,
                     "%.4f" % rd if rd else "-",
                     "%.4f" % cd if cd else "-",
                     ratio(cd, rd),
                     "%.4f" % rs if rs else "-",
                     "%.4f" % cs if cs else "-",
                     ratio(cs, rs)))
            w()

    if args.output:
        out.close()


if __name__ == "__main__":
    main()
