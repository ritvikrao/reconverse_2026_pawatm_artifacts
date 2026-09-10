#!/usr/bin/env python3
"""Plot the pingpong latency and bandwidth curves.

Data source is the per-trial run logs in cr_pingpong_final/raw rather than the
formatted tables beside them, so the statistic is ours to choose: one log per
(placement, version), each holding 5 reps of 23 message sizes, keyed by the
'=== place ... rep N ===' banners the run script emits.

The reps are reduced by MEDIAN, matching both the tables in
pingpong_results.txt and the methods paragraph in the paper. --aggregate mean
switches to the arithmetic mean, but the intra-node reps at large sizes are
bimodal rather than merely noisy -- 1-node old Converse at 64 MB reads
11.04, 11.04, 19.46, 11.04, 19.58 ms, two tight clusters 1.8x apart -- so a
mean there reports the midpoint of a mixture no single run ever exhibits, and
lands 30.7% above the median. The median names one of the two real states.

Both placements come from the same job and the same four builds, so unlike
the earlier two-file runs there is one column mapping for both.

Two figures, one per placement, each a pair of panels sharing one legend:

  pingpong_1_node.pdf   2 processes on 1 physical node  (intra-node)
  pingpong_2_node.pdf   2 processes on 2 physical nodes (inter-node)

Left panel is one-way latency, right panel is effective bandwidth. They are two
different measures on two different scales, so they get two panels rather than
two y-axes on one plot.

Plus the bandwidth panel on its own, a full column wide, for the case where the
paper only has room to make the bandwidth point:

  pingpong_1_node_bandwidth.pdf
  pingpong_2_node_bandwidth.pdf

Four series per figure. The supplementary 8-device arm is not plotted: it
tracks the 1-device message path within noise (see note 5 in
pingpong_results.txt) and a fifth curve would push the palette past what
clears the all-pairs colourblind gate.

Figures carry no title — they are captioned in the paper.

Usage: python3 plot_pingpong.py [output_dir] [raw_data_dir]
                                [--aggregate median|mean]
"""

import argparse
import math
import re
import statistics
from collections import OrderedDict
from pathlib import Path

from matplotlib.ticker import FuncFormatter

import plotstyle as ps

DATA_DIR = Path("cr_pingpong_final/raw")

# How the 5 reps at each message size are reduced to the plotted point.
AGGREGATORS = {"median": statistics.median, "mean": statistics.fmean}
DEFAULT_AGGREGATE = "median"

# The banner the run script writes before each repetition, and the one result
# line per message size that follows it.
REP_BANNER = re.compile(r"^=== place (?P<place>\w+) version (?P<version>\w+) rep (?P<rep>\d+) ===")
RESULT = re.compile(r"^Size=(?P<bytes>\d+) bytes, time=(?P<us>[\d.]+) microseconds one-way")

REPS_EXPECTED = 5

# legend label -> (colour, line style, marker). One style per label, so a
# reader can carry identity from one figure to the other.
#
# A fourth categorical hue would put yellow beside orange, which fails the
# all-pairs gate, so violet takes the fourth slot and line style is the second
# cue that separates its closest neighbour (blue). Validated all-pairs in light
# mode: worst CVD ΔE 9.2, worst normal-vision ΔE 16.3. Aqua sits at 2.74:1 on
# this surface, so the legend is required — colour is never the only label.
COLOR_VIOLET = "#4a3aa7"

SERIES = OrderedDict([
    ("Old Converse",             (ps.COLOR_BLUE,   "-",  "o")),
    ("Reconverse",               (ps.COLOR_ORANGE, "-",  "o")),
    ("Reconverse RDMA",          (ps.COLOR_AQUA,   "--", "s")),
    ("Reconverse persist+RDMA",  (COLOR_VIOLET,    "-.", "^")),
])

# legend label -> the `version` token in the log banners and file names.
# 'recon_normal_nd8' is the supplementary 8-device arm and is deliberately
# absent; see the module docstring.
VERSIONS = OrderedDict([
    ("Old Converse",            "converse"),
    ("Reconverse",              "recon_normal"),
    ("Reconverse RDMA",         "recon_rdma"),
    ("Reconverse persist+RDMA", "recon_persist"),
])

# node count -> the `place` token in the log banners and file names.
PLACEMENTS = OrderedDict([(1, "1node"), (2, "2node")])

# The range is 8 doublings wider than the earlier runs, so the byte labels are
# wider too ("32M", "512K") and fewer of them fit: at 4 per half-panel "256K"
# and "32M" touch, and at 8 on a full column "64K" and "512K" do.
MAX_X_LABELS = 3     # per panel in the paired figure
SINGLE_X_LABELS = 6  # a full column has room for every fourth power of two
DENSE_TICK_DECADES = 1.5  # up to this span a 1-2-5 y sequence still fits
FIGURE_ASPECT = 0.62


def parse(path):
    """Return {(place, version): {rep: {size_bytes: latency_us}}} from one log.

    Both keys come from the banner rather than the file name, so a log holding
    more than one configuration parses correctly and a mislabelled file is
    caught by the caller rather than silently attributed.
    """
    runs = {}
    current = None
    for line in path.read_text().splitlines():
        match = REP_BANNER.match(line)
        if match:
            key = (match.group("place"), match.group("version"))
            current = runs.setdefault(key, {}).setdefault(int(match.group("rep")), {})
            continue
        match = RESULT.match(line)
        if match and current is not None:
            current[int(match.group("bytes"))] = float(match.group("us"))
    return runs


def load(data_dir, aggregate=DEFAULT_AGGREGATE):
    """Return {(place, version): (sizes, latency_us)}, reps reduced by `aggregate`.

    Every rep must cover the same message sizes; a short or ragged rep means a
    run died partway and reducing it against the others would quietly bias the
    curve, so it is an error rather than a shorter series.
    """
    reduce = AGGREGATORS[aggregate]
    logs = sorted(p for p in data_dir.glob("*.log") if p.stem != "smoke")
    if not logs:
        raise SystemExit(f"no run logs in {data_dir}")

    series = {}
    for path in logs:
        for (place, version), reps in parse(path).items():
            if (place, version) in series:
                raise SystemExit(f"{place}/{version} appears in more than one log")
            if len(reps) != REPS_EXPECTED:
                raise SystemExit(
                    f"{path.name}: {place}/{version} has {len(reps)} reps, "
                    f"expected {REPS_EXPECTED}"
                )
            size_sets = {tuple(sorted(rep)) for rep in reps.values()}
            if len(size_sets) != 1:
                raise SystemExit(
                    f"{path.name}: {place}/{version} reps cover different message sizes"
                )
            sizes = list(size_sets.pop())
            if not sizes:
                raise SystemExit(f"{path.name}: {place}/{version} has no data rows")
            latency = [reduce([rep[size] for rep in reps.values()]) for size in sizes]
            series[(place, version)] = (sizes, latency)
    return series


def bandwidth(sizes, latency_us):
    """Effective bandwidth in MB/s: size / aggregated one-way time, as in the tables.

    Deriving it from the aggregated latency rather than aggregating the per-rep
    bandwidths keeps the two panels exact transforms of one another. On the
    median the distinction is vacuous anyway: size/t is monotone in t, and a
    monotone map carries the middle observation to the middle observation, so
    size/median(t) IS the median per-rep bandwidth. (For the mean it is the
    harmonic mean of the per-rep bandwidths, which is still the right way to
    average a rate.)

    bytes/µs is MB/s on the decimal MB the tables use.
    """
    return [size / us for size, us in zip(sizes, latency_us)]


def format_bytes(value, _pos=None):
    """Power-of-two sizes as 16 / 1K / 256K, exactly (never 1.02K)."""
    size = int(round(value))
    for suffix, scale in (("M", 1 << 20), ("K", 1 << 10)):
        if size >= scale and size % scale == 0:
            return f"{size // scale}{suffix}"
    return f"{size}"


def even_ticks(values, max_labels):
    """Evenly spaced entries of `values`, starting at the first.

    Unlike ps.thinned this does not force the last value in: on a half-width
    panel the forced endpoint lands one or two steps from its neighbour and the
    two labels overlap.
    """
    stride = max(1, (len(values) - 1) // (max_labels - 1))
    return values[::stride]


def decade_ticks(low, high):
    """One tick per decade over [low, high] — all that fits on a half-panel."""
    first = math.floor(math.log10(low))
    last = math.ceil(math.log10(high))
    return [10.0 ** e for e in range(first, last + 1)]


def y_ticks(low, high):
    """1-2-5 while the data is shallow, one per decade once it is not.

    The runs now reach 64 MB, so both latency and bandwidth span four to five
    decades and a 1-2-5 sequence would be a dozen labels on a two-inch axis.
    The threshold keeps the denser sequence available for the narrower ranges
    the earlier, shorter runs produced.
    """
    if math.log10(high / low) <= DENSE_TICK_DECADES:
        return ps.log_ticks(low, high)
    return decade_ticks(low, high)


def draw_panel(ax, sizes, series, ylabel, max_x_labels=MAX_X_LABELS, xlabel=None):
    """`series` is {legend label: values}, one entry per SERIES key."""
    for label, (color, linestyle, marker) in SERIES.items():
        ps.series_line(
            ax, sizes, series[label],
            color=color, linestyle=linestyle, marker=marker, label=label,
        )

    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.xaxis.set_major_formatter(FuncFormatter(format_bytes))
    ax.set_xticks(even_ticks(sizes, max_x_labels))
    ax.minorticks_off()
    ps.pad_log_x(ax, sizes)

    values = [v for label in SERIES for v in series[label]]
    ax.set_yticks(y_ticks(min(values), max(values)))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:g}"))
    ax.set_ylim(min(values) / 1.35, max(values) * 1.35)

    ps.style_axes(ax, xlabel=xlabel, ylabel=ylabel)


def plot_bandwidth(sizes, panels, out_path):
    """Bandwidth on its own, one full column-width plot.

    A whole column for one measure buys back the x labels the paired figure has
    to drop.
    """
    fig, ax = ps.new_figure()
    draw_panel(
        ax, sizes, panels["bandwidth"], "Bandwidth (MB/s)",
        max_x_labels=SINGLE_X_LABELS, xlabel="Message size (bytes)",
    )
    ps.legend_above(ax, ncol=1)
    ps.save(fig, out_path)


def plot(sizes, panels, out_path):
    fig, axes = ps.new_panel_row(
        2, aspect=FIGURE_ASPECT, fraction=ps.FIGURE_FRACTION,
        sharey=False, sharex=False,
    )

    draw_panel(axes[0], sizes, panels["latency"], "One-way latency (µs)")
    draw_panel(axes[1], sizes, panels["bandwidth"], "Bandwidth (MB/s)")

    fig.supxlabel("Message size (bytes)", color=ps.TEXT_SECONDARY,
                  fontsize=ps.FONT_AXIS_LABEL)
    ps.legend_above(axes[0], ncol=2)
    ps.save(fig, out_path)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", nargs="?", default=".", type=Path)
    parser.add_argument("data_dir", nargs="?", default=DATA_DIR, type=Path)
    parser.add_argument(
        "--aggregate", choices=sorted(AGGREGATORS), default=DEFAULT_AGGREGATE,
        help="how to reduce the 5 reps at each size (default: %(default)s)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    ps.use_paper_style()

    measured = load(args.data_dir, args.aggregate)

    for nodes, place in PLACEMENTS.items():
        missing = [v for v in VERSIONS.values() if (place, v) not in measured]
        if missing:
            raise SystemExit(f"{place}: no logs for versions {missing}")

        size_sets = {tuple(measured[(place, v)][0]) for v in VERSIONS.values()}
        if len(size_sets) != 1:
            raise SystemExit(f"{place}: versions cover different message sizes")
        sizes = list(size_sets.pop())

        panels = {"latency": OrderedDict(), "bandwidth": OrderedDict()}
        for label, version in VERSIONS.items():
            _, latency = measured[(place, version)]
            panels["latency"][label] = latency
            panels["bandwidth"][label] = bandwidth(sizes, latency)

        plot(sizes, panels, out_dir / f"pingpong_{nodes}_node.pdf")
        plot_bandwidth(
            sizes, panels, out_dir / f"pingpong_{nodes}_node_bandwidth.pdf"
        )


if __name__ == "__main__":
    main()
