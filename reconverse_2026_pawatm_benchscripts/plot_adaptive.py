#!/usr/bin/env python3
"""Plot the adaptive queue-polling results from adaptive_results.txt.

Four column-width grouped bar charts, one per benchmark and PE count:

  adaptive_bench1_4pe.pdf   adaptive_bench1_8pe.pdf   grouped by stream count
  adaptive_bench2_4pe.pdf   adaptive_bench2_8pe.pdf   grouped by (x, y) mix

Each group carries the count, static and Converse timings; the hitrate column
is not plotted. Figures carry no title — they are captioned in the paper.

Usage: python3 plot_adaptive.py [adaptive_results.txt] [output_dir]
"""

import re
import sys
from collections import OrderedDict
from pathlib import Path

import plotstyle as ps

BENCHMARK = re.compile(r"^Benchmark (\d+):")
PE_SECTION = re.compile(r"^(\d+) PEs? -- (?P<what>.+?) \((?P<unit>[^,)]+), lower is better\)")

# The one header line that names all four measurement columns; the paired
# comparison tables below it name different columns and are skipped.
COLUMN_HEADER = re.compile(r"^\s*(streams|step)\b.*hitrate.*Converse\s*$")

# Plotted series, in bar order within a group (and so in legend order), with
# their column names. Reversed relative to the source table's column order.
SERIES = OrderedDict([
    ("Converse", ("Converse", ps.COLOR_BLUE)),
    ("static", ("Static", ps.COLOR_ORANGE)),
    ("count", ("Adaptive (count)", ps.COLOR_AQUA)),
])

GROUP_WIDTH = 0.78


def parse(path):
    """Return {(benchmark, pe): {"ylabel": str, "groups": [(label, {col: v})]}}."""
    tables = OrderedDict()
    benchmark = None
    current = None
    columns = None

    for line in path.read_text().splitlines():
        match = BENCHMARK.match(line)
        if match:
            benchmark = int(match.group(1))
            current = None
            continue

        match = PE_SECTION.match(line)
        if match:
            if benchmark is None:
                raise ValueError(f"PE section before any benchmark heading: {line!r}")
            unit = "µs" if match.group("unit") == "us" else match.group("unit")
            what = match.group("what").strip()
            current = tables.setdefault((benchmark, int(match.group(1))), {
                "ylabel": f"{what[0].upper()}{what[1:]} ({unit})",
                "groups": [],
            })
            columns = None
            continue

        if current is None:
            continue

        if COLUMN_HEADER.match(line):
            columns = line.split()
            continue

        if columns is None:
            continue

        fields = line.split()
        if len(fields) != len(columns) or not all(_is_number(f) for f in fields):
            if current["groups"]:
                columns = None  # table finished
            continue

        row = dict(zip(columns, (float(f) for f in fields)))
        if columns[0] == "streams":
            label = f"{int(row['streams'])}"
        else:
            label = f"x={int(row['x'])}, y={int(row['y'])}"
        current["groups"].append((label, row))

    return tables


def _is_number(token):
    try:
        float(token)
    except ValueError:
        return False
    return True


def plot(table, xlabel, out_path, rotate_labels, aspect):
    groups = table["groups"]
    labels = [label for label, _ in groups]
    n = len(SERIES)
    bar_width = GROUP_WIDTH / n

    fig, ax = ps.new_figure(aspect=aspect)

    for index, (column, (name, color)) in enumerate(SERIES.items()):
        offsets = [
            i - GROUP_WIDTH / 2 + bar_width * (index + 0.5) for i in range(len(groups))
        ]
        ax.bar(
            offsets, [row[column] for _, row in groups],
            width=bar_width * 0.88,  # the gap that keeps adjacent bars separate
            color=color, label=name, zorder=3, linewidth=0,
        )

    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels(labels)
    if rotate_labels:
        # Nine "x=16, y=0" labels do not fit side by side at column width.
        for label in ax.get_xticklabels():
            label.set_rotation(45)
            label.set_ha("right")
            label.set_rotation_mode("anchor")
    ax.set_xlim(-0.5 - GROUP_WIDTH / 4, len(groups) - 0.5 + GROUP_WIDTH / 4)

    ps.style_axes(ax, xlabel, table["ylabel"])
    ax.grid(False, axis="x")  # categorical axis: gridlines would imply a scale
    ps.legend_above(ax, ncol=n)
    ps.save(fig, out_path)


def main():
    results_path = Path(
        sys.argv[1] if len(sys.argv) > 1
        else "adaptive_20260730_final/adaptive_results.txt"
    )
    out_dir = Path(sys.argv[2] if len(sys.argv) > 2 else ".")
    out_dir.mkdir(parents=True, exist_ok=True)
    ps.use_paper_style()

    tables = parse(results_path)
    expected = [(b, pe) for b in (1, 2) for pe in (4, 8)]
    missing = [key for key in expected if key not in tables]
    if missing:
        raise SystemExit(f"no table found for (benchmark, PEs) {missing}")

    for (benchmark, pe), table in tables.items():
        for label, row in table["groups"]:
            absent = [c for c in SERIES if c not in row]
            if absent:
                raise SystemExit(
                    f"benchmark {benchmark}, {pe} PE, group {label!r}: missing {absent}"
                )
        plot(
            table,
            xlabel="Local streams per PE" if benchmark == 1 else "Queue occupancy mix",
            out_path=out_dir / f"adaptive_bench{benchmark}_{pe}pe.pdf",
            rotate_labels=benchmark == 2,
            # Benchmark 2's rotated labels need the extra height, or they eat
            # into the plot area.
            aspect=0.80 if benchmark == 1 else 0.95,
        )


if __name__ == "__main__":
    main()
