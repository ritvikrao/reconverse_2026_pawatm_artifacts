#!/usr/bin/env python3
"""Turn the raw pingpong logs into a latency/bandwidth table.

Each run prints one line per message size:

    Size=<bytes> bytes, time=<t> microseconds one-way

which is the half-round-trip time averaged over the run's iterations.  Points
are reported as the MEDIAN over repetitions: this machine's per-run variation
is not gaussian (see bench_results/README.md), so a mean is dragged around by
however many slow repetitions a configuration happened to catch.

Bandwidth is derived from the same measurement, size / one-way time, so it
carries no independent information -- it is just the more readable view at the
large-message end, where latency is dominated by transfer rather than by
per-message cost.
"""

import argparse
import collections
import os
import re
import statistics
import sys

HEADER = re.compile(r"^=== place (\S+) version (\S+) rep (\d+) ===$", re.M)
POINT = re.compile(r"^Size=(\d+) bytes, time=([0-9.eE+-]+) microseconds one-way$",
                   re.M)

VERSION_LABEL = collections.OrderedDict([
    ("converse", "old Converse"),
    ("recon_normal", "Reconverse msg"),
    ("recon_rdma", "Reconverse RDMA"),
    ("recon_persist", "Reconverse persist+RDMA"),
    ("recon_normal_nd8", "Reconverse msg (8 dev)"),
    ("recon_normal_shm", "Reconverse msg +SHM"),
    ("recon_rdma_shm", "Reconverse RDMA +SHM"),
    ("recon_persist_shm", "Reconverse persist +SHM"),
    ("recon_normal_shm8k", "Reconverse msg +SHM 8K slot"),
])

PLACE_LABEL = {
    "1node": "2 processes on 1 physical node (intra-node)",
    "2node": "2 processes on 2 physical nodes (inter-node)",
}


def load(raw_dir):
    """(place, version, size) -> list of one-way us, one per repetition."""
    data = collections.defaultdict(list)
    reps = collections.defaultdict(set)
    for name in sorted(os.listdir(raw_dir)):
        if not name.endswith(".log") or name == "smoke.log":
            continue
        text = open(os.path.join(raw_dir, name)).read()
        marks = list(HEADER.finditer(text))
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            place, ver, rep = m.group(1), m.group(2), int(m.group(3))
            body = text[m.end():end]
            for size, t in POINT.findall(body):
                data[(place, ver, int(size))].append(float(t))
                reps[(place, ver)].add(rep)
    return data, reps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args()

    raw = os.path.join(args.results_dir, "raw")
    data, reps = load(raw)
    if not data:
        sys.exit("no parseable pingpong runs in %s" % raw)

    out = open(args.output, "w") if args.output else sys.stdout
    def w(line=""):
        print(line, file=out)

    places = [p for p in ("1node", "2node") if any(k[0] == p for k in data)]
    versions = [v for v in VERSION_LABEL if any(k[1] == v for k in data)]
    sizes = sorted({k[2] for k in data})
    nreps = max((len(v) for v in reps.values()), default=0)

    w("Pingpong: one-way message latency")
    w("=" * 78)
    w()
    w("Machine   : NCSA Delta CPU nodes, 2x AMD EPYC 7763, HPE Slingshot")
    w("Iterations: 1000 per message size")
    w("Sizes     : 16 to 262144 bytes, doubling")
    w("Statistic : median of %d repetitions" % nreps)
    w()
    w("Layout    : 2 processes, 1 PE each, in both sets.  The two sets differ")
    w("            only in whether those processes share a physical node.")
    w()
    w("Versions:")
    w("  old Converse             charm/benchmarks/converse/pingpong, built")
    w("                           -optimize -production -O3 against the")
    w("                           mpi-linux-x86_64-smp build")
    w("  Reconverse msg           tests/orig-converse/pingpong -- the same")
    w("                           benchmark on the ordinary send path")
    w("  Reconverse RDMA          tests/rdma_pingpong -- explicit one-sided")
    w("                           get on a registered CmiNcpyBuffer, with a")
    w("                           small message carrying the completion signal")
    w("  Reconverse persist+RDMA  tests/persistent_pingpong -- the message")
    w("                           benchmark with the timed sends routed")
    w("                           through a PersistentHandle, which registers")
    w("                           its receive buffers once at setup and moves")
    w("                           the payload with a one-sided put")
    w()
    w("Reconverse is built CMAKE_BUILD_TYPE=Release with autofetched LCI v2,")
    w("from `main` plus the new persistent pingpong only.  Both processes are")
    w("given 2 cores in every configuration, so the Converse comm thread does")
    w("not change the placement relative to Reconverse, which has no comm")
    w("thread.")
    w()
    w("LCI shared memory: builds marked +SHM are configured -DLCI_WITH_SHM=ON,")
    w("which enables LCI's experimental POSIX shared-memory transport and, per")
    w("binding.cpp:159, turns it on by default with no runtime flag.  Its")
    w("default slot size is 128 bytes and the usable size is min(slot payload,")
    w("packet payload), so only the smallest messages take the SHM path; the")
    w("'8K slot' arm raises LCI_ATTR_SHM_SLOT_SIZE to 8192 to cover more of")
    w("the sweep.")
    w()
    w("The persistent row is from the build WITHOUT SHM.  Persistent + SHM")
    w("faults (SIGABRT or SIGSEGV, 5 of 5 trials), so there is no persistent")
    w("+SHM measurement to report; that row is the non-SHM build, run in the")
    w("same job as everything else so it stays paired.")
    w()
    w("LCI devices: the four compared versions all run +lci_ndevices 1, NOT")
    w("the 8 used for the task-bench runs.  Above one device the one-sided")
    w("get aborts inside LCI:")
    w()
    w("    backend_ofi_inline.hpp:post_get_impl:388")
    w("      <lci:Assert failed: false> err : Invalid argument")
    w()
    w("because the memory region is registered against one device while the")
    w("get is posted on another.  It reproduces at 2 devices and at 8, and")
    w("not at 1 or at the default, which is why reconverse's own CMake test")
    w("for rdma_pingpong passes no device flag.  Running two versions at 8")
    w("and two at 1 would make the columns incomparable, so all four use 1.")
    w("With one PE per process there is no concurrency for extra devices to")
    w("exploit in any case.")
    w()
    w("'Reconverse msg (8 dev)' is a supplementary fifth arm, not one of the")
    w("eight configurations: it is the message path at 8 devices, to show")
    w("what the device count is worth where it does work.")
    w()

    for place in places:
        w("=" * 78)
        w(PLACE_LABEL.get(place, place))
        w("=" * 78)
        w()
        w("one-way latency, microseconds (lower is better)")
        w()
        w("%10s %s" % ("bytes", "".join("%24s" % VERSION_LABEL[v]
                                        for v in versions)))
        for size in sizes:
            row = "%10d" % size
            for v in versions:
                vals = data.get((place, v, size))
                row += "%24s" % ("%.3f" % statistics.median(vals) if vals else "-")
            w(row)
        w()

        base = "converse"
        if base in versions and len(versions) > 1:
            others = [v for v in versions if v != base]
            w("speedup vs old Converse (>1 means the Reconverse version is faster)")
            w()
            w("%10s %s" % ("bytes", "".join("%24s" % VERSION_LABEL[v]
                                            for v in others)))
            for size in sizes:
                row = "%10d" % size
                b = data.get((place, base, size))
                for v in others:
                    vals = data.get((place, v, size))
                    if vals and b:
                        row += "%23.2fx" % (statistics.median(b) /
                                            statistics.median(vals))
                    else:
                        row += "%24s" % "-"
                w(row)
            w()

        w("effective bandwidth, MB/s (size / one-way time)")
        w()
        w("%10s %s" % ("bytes", "".join("%24s" % VERSION_LABEL[v]
                                        for v in versions)))
        for size in sizes:
            row = "%10d" % size
            for v in versions:
                vals = data.get((place, v, size))
                if vals:
                    row += "%24.1f" % (size / statistics.median(vals))
                else:
                    row += "%24s" % "-"
            w(row)
        w()
        w("spread across repetitions, (max-min)/min as a percentage")
        w()
        w("%10s %s" % ("bytes", "".join("%24s" % VERSION_LABEL[v]
                                        for v in versions)))
        for size in sizes:
            row = "%10d" % size
            for v in versions:
                vals = data.get((place, v, size))
                if vals and len(vals) > 1 and min(vals) > 0:
                    row += "%23.1f%%" % (100.0 * (max(vals) - min(vals)) / min(vals))
                else:
                    row += "%24s" % "-"
            w(row)
        w()

    w("=" * 78)
    w("Notes")
    w("=" * 78)
    w()
    w("Repetition spread is 2-16%, so the large ratios below are well clear")
    w("of the noise while anything inside roughly 0.85-1.15x is not.")
    w()
    w("1. The two placements give opposite answers at small messages, and")
    w("   that is the headline result.  Intra-node, old Converse is about")
    w("   2x faster than Reconverse's message path (2.0 vs 3.7 us at 64")
    w("   bytes): both are shared-memory copies, and Converse's is leaner.")
    w("   Inter-node, that reverses -- Reconverse is about 2.4x faster (3.5")
    w("   vs 8.6 us), because the Charm++ build goes through MPI while")
    w("   Reconverse goes to libfabric through LCI.  A single-number")
    w("   comparison of the two runtimes would hide this completely.")
    w()
    w("2. The message path has a latency cliff between 4 KB and 8 KB")
    w("   (7.4 -> 17.3 us inter-node, 7.2 -> 16.8 intra-node).  That is the")
    w("   eager-to-rendezvous switch, and it lands exactly at the")
    w("   LCI_ATTR_PACKET_SIZE=8192 carried over from the task-bench runs:")
    w("   messages larger than one packet stop being sent eagerly.  Neither")
    w("   the RDMA nor the persistent version shows the cliff, since both")
    w("   move the payload one-sided and never take the eager path.  The")
    w("   cliff is a property of that setting, not of the runtime -- raising")
    w("   LCI_ATTR_PACKET_SIZE would move it.")
    w()
    w("3. The persistent channel is the best large-message option and the")
    w("   only version that wins at 256 KB in both placements (3.34x")
    w("   intra-node, 1.28x inter-node vs old Converse).  It beats plain")
    w("   RDMA there because the receive buffers are registered once at")
    w("   setup rather than per transfer.")
    w()
    w("4. Below about 2 KB the persistent and RDMA versions are the slowest")
    w("   of the four.  Both pay a round trip for the completion signal on")
    w("   top of the transfer, which dominates when the payload is small;")
    w("   one-sided transport only pays off once the payload is large")
    w("   enough for that fixed cost to amortise.")
    w()
    w("5. The supplementary 8-device arm is within noise of the 1-device")
    w("   message path at every size, so pinning all four versions to 1")
    w("   device to accommodate the RDMA limitation costs nothing here.")
    w()

    if args.output:
        out.close()


if __name__ == "__main__":
    main()
