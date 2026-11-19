"""Static figures for the report (matplotlib, PNG)."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_MUTED = "#52514e"
GRID = "#e4e3df"
CANDIDATE = "#c3c2b7"
SELECTED = "#2a78d6"


def _style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=TEXT_MUTED, labelsize=9)
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _draw_geom(ax, geom, **kw):
    from shapely.geometry import MultiPolygon
    for p in (geom.geoms if isinstance(geom, MultiPolygon) else [geom]):
        x, y = p.exterior.xy
        ax.fill(x, y, **kw)


def plot_round0_gallery(rows, specs: dict, path) -> Path:
    """One row per country: the reference, then each sample's drawing over the reference outline.

    Shapes are aligned the way they are scored (centroid at origin, area 1), so overlap reads as IoU.
    """
    from geometry import align, svg_to_geometry
    from groundtruth import load_reference

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    countries = list(dict.fromkeys(r["country"] for r in rows))
    n_samples = max(r["sample"] for r in rows) + 1
    fig, axes = plt.subplots(len(countries), n_samples + 1, figsize=(2.4 * (n_samples + 1), 2.4 * len(countries)),
                             dpi=110, squeeze=False)
    fig.patch.set_facecolor(SURFACE)
    for i, name in enumerate(countries):
        ref = align(load_reference(specs[name]))
        ax = axes[i, 0]
        _draw_geom(ax, ref, facecolor="#d9d8d3", edgecolor=TEXT, linewidth=0.8)
        ax.set_title(f"{name}\nreference", fontsize=8, color=TEXT)
        for s in range(n_samples):
            ax = axes[i, s + 1]
            row = next((r for r in rows if r["country"] == name and r["sample"] == s), None)
            if row is None:
                ax.set_title("not run", fontsize=8, color=TEXT_MUTED)
                continue
            geom = svg_to_geometry(row["svg"]) if row["svg"] else None
            if geom is not None:
                _draw_geom(ax, align(geom), facecolor=SELECTED, alpha=0.45, edgecolor=SELECTED, linewidth=0.8)
            _draw_geom(ax, ref, facecolor="none", edgecolor=TEXT, linewidth=0.8)
            label = f"IoU {row['iou']:.2f}  HD95 {row['hd95']:.2f}" if row["valid"] else "invalid output"
            ax.set_title(f"sample {s}\n{label}", fontsize=8, color=TEXT)
    for ax in axes.flat:
        ax.set_aspect("equal")
        ax.axis("off")
    fig.suptitle("Round 0 drawings (blue) over the reference outline (black), aligned as scored",
                 fontsize=10, color=TEXT, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path


LABEL_OFFSETS =[((5, 3), "left"), ((5, -11), "left"), ((-5, 3), "right"), ((-5, -11), "right"),
                 ((5, 12), "left"), ((-5, 12), "right")]


def _place_labels(fig, ax, xs, ys, names):
    """Label points, trying offsets in turn and keeping the first that overlaps no earlier label."""
    renderer = fig.canvas.get_renderer()
    placed = []
    for x, y, name in sorted(zip(xs, ys, names), key=lambda t: -t[1]):
        for offset, ha in LABEL_OFFSETS:
            t = ax.annotate(name, (x, y), xytext=offset, textcoords="offset points", ha=ha,
                            fontsize=8, color=TEXT, zorder=4)
            box = t.get_window_extent(renderer).expanded(1.05, 1.15)
            if not any(box.overlaps(b) for b in placed):
                placed.append(box)
                break
            t.remove()
        else:
            placed.append(ax.annotate(name, (x, y), xytext=LABEL_OFFSETS[0][0], textcoords="offset points",
                                      fontsize=8, color=TEXT, zorder=4).get_window_extent(renderer))


def plot_country_selection(df, path) -> Path:
    """Familiarity (log pageviews) vs complexity for all eligible countries; the picks are labelled.

    Quadrants are the median splits, so a pick's cell is its position on the plot.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = df[df["excluded"] == ""]
    sel = ok[ok["selected"]]

    fig, ax = plt.subplots(figsize=(9, 6.5), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)

    x_med = np.median(ok["complexity_score"])
    y_med = np.median(ok["pageviews"])
    ax.axvline(x_med, color=TEXT_MUTED, linewidth=1)
    ax.axhline(y_med, color=TEXT_MUTED, linewidth=1)

    ax.scatter(ok["complexity_score"], ok["pageviews"], s=22, color=CANDIDATE,
               edgecolor=SURFACE, linewidth=1, label=f"Eligible, not picked ({len(ok) - len(sel)})", zorder=2)
    ax.scatter(sel["complexity_score"], sel["pageviews"], s=40, color=SELECTED,
               edgecolor=SURFACE, linewidth=1.5, label=f"Picked ({len(sel)})", zorder=3)
    ax.set_yscale("log")
    _place_labels(fig, ax, sel["complexity_score"], sel["pageviews"], sel["name"])
    ax.set_xlabel("Shape complexity (mean percentile of roughness and concavity)", color=TEXT, fontsize=10)
    ax.set_ylabel("English Wikipedia pageviews, last 60 days (log)", color=TEXT, fontsize=10)
    ax.set_title("Country selection: familiarity x shape complexity", color=TEXT, fontsize=12, loc="left")

    corners = {"popular / simple": (0.01, 0.98, "left", "top"), "popular / complex": (0.99, 0.98, "right", "top"),
               "niche / simple": (0.01, 0.02, "left", "bottom"), "niche / complex": (0.99, 0.02, "right", "bottom")}
    for text, (x, y, ha, va) in corners.items():
        ax.text(x, y, text, transform=ax.transAxes, ha=ha, va=va, fontsize=9, color=TEXT_MUTED)

    leg = ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=2, frameon=False, fontsize=9)
    for t in leg.get_texts():
        t.set_color(TEXT)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path
