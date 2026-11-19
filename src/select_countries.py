"""Pick the experiment's countries on a 2x2 grid of familiarity x shape complexity (D-009).

Usage:
  python src/select_countries.py --fetch   # query Wikipedia, then select
  python src/select_countries.py           # reuse data/familiarity/pageviews.csv

Writes configs/countries.yaml, data/familiarity/candidates.csv and analysis/figures/country_selection.png.
"""
import argparse
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
import yaml
from shapely.geometry import MultiPolygon, Point

from draw_test import COUNTRIES
from geometry import align
from groundtruth import ROOT, load_reference, lookup, unproject
from metrics import score

OVERRIDES_FILE = ROOT / "configs" / "scope_overrides.yaml"
COUNTRIES_FILE = ROOT / "configs" / "countries.yaml"
PAGEVIEWS_FILE = ROOT / "data" / "familiarity" / "pageviews.csv"
CANDIDATES_FILE = ROOT / "data" / "familiarity" / "candidates.csv"
FIGURE_FILE = ROOT / "analysis" / "figures" / "country_selection.png"

PER_CELL = 6
MIN_AREA_KM2 = 10_000          # smaller countries count as microstates
MAX_PARTS = 5                  # more kept parts counts as an archipelago
MAX_PART_GAP_KM = 1_000        # a kept part this far from the largest needs a hand-written scope
SIMPLIFY_TOL = 0.01            # in units of sqrt(area), so complexity is scale-free
PAGEVIEW_DAYS = 60             # the most the MediaWiki pageviews prop returns
USER_AGENT = "cs598-country-selection/0.1 (student course project)"

# Natural Earth names that differ from the prompt name.
NE_NAMES = {"Cote d'Ivoire": "Ivory Coast", "Sao Tome and Principe": "São Tomé and Principe"}
# English Wikipedia articles whose title differs from the prompt name.
WIKI_TITLES = {
    "Georgia": "Georgia (country)", "Ireland": "Republic of Ireland",
    "Micronesia": "Federated States of Micronesia", "Palestine": "State of Palestine",
    "Gambia": "The Gambia", "Bahamas": "The Bahamas", "Cabo Verde": "Cape Verde",
    "Timor-Leste": "East Timor", "Cote d'Ivoire": "Ivory Coast", "Czechia": "Czech Republic",
    "Sao Tome and Principe": "São Tomé and Príncipe",
}

# Outline depends on which side of a major territorial dispute is drawn; Natural Earth draws de facto lines.
DISPUTED = {
    "Armenia", "Azerbaijan", "China", "Cyprus", "Georgia", "India", "Israel", "Morocco", "Pakistan",
    "Palestine", "Russia", "Serbia", "Somalia", "South Sudan", "Sudan", "Ukraine",
}

CELLS = [("popular", "simple"), ("popular", "complex"), ("niche", "simple"), ("niche", "complex")]


# --- geometry -------------------------------------------------------------------------------

def _sinusoidal_km(geom):
    """Equal-area projection in km, for areas."""
    def f(c):
        lat = np.radians(c[:, 1])
        return np.column_stack([6371.0 * np.radians(c[:, 0]) * np.cos(lat), 6371.0 * lat])
    return shapely.transform(geom, f)


def _local_km(geom, lon0, lat0):
    """Local flat projection in km around (lon0, lat0), for distances between parts."""
    k = math.cos(math.radians(lat0))
    return shapely.transform(geom, lambda c: np.column_stack([(c[:, 0] - lon0) * 111.32 * k,
                                                              (c[:, 1] - lat0) * 110.57]))


def _parts(geom):
    return list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]


def default_spec(name: str) -> dict:
    spec = {"name": name}
    if name in NE_NAMES:
        spec["ne_name"] = NE_NAMES[name]
    return spec


def complexity(ref) -> dict:
    """Scale-free shape measures on the aligned, simplified reference."""
    g = align(ref).simplify(SIMPLIFY_TOL)
    return {
        "roughness": g.length / g.convex_hull.length - 1,          # boundary excess over the hull; 0 for convex
        "concavity": 1 - g.area / g.convex_hull.area,
        "disc_iou": score(Point(0, 0).buffer(1, 256), ref)["iou"],  # blob floor, D-019
    }


def candidate_table() -> pd.DataFrame:
    overrides = {c["name"]: c for c in yaml.safe_load(OVERRIDES_FILE.read_text("utf-8"))["countries"]}
    rows = []
    for name in COUNTRIES:
        spec = overrides.get(name, default_spec(name))
        row = {"name": name, "ne_name": spec.get("ne_name", name), "override": name in overrides}
        try:
            _, raw = lookup(row["ne_name"])
        except KeyError:
            rows.append({**row, "excluded": "not in Natural Earth 1:50m"})
            continue
        row["area_km2"] = round(_sinusoidal_km(raw).area)
        ref = load_reference(spec)
        parts = _parts(ref)
        row["parts"] = len(parts)
        row["raw_parts"] = len(_parts(raw))

        # Distance from every kept part to the largest one, in lon/lat space around the country.
        ll = [unproject(p) for p in parts]
        c = shapely.union_all(ll).centroid
        km = [_local_km(p, c.x, c.y) for p in ll]
        main = max(km, key=lambda p: p.area)
        row["max_part_gap_km"] = round(max(main.distance(p) for p in km))
        row.update(complexity(ref))

        if row["area_km2"] < MIN_AREA_KM2:
            row["excluded"] = f"microstate (< {MIN_AREA_KM2:,} km2)"
        elif row["parts"] > MAX_PARTS:
            row["excluded"] = f"archipelago (> {MAX_PARTS} parts)"
        elif row["max_part_gap_km"] > MAX_PART_GAP_KM and not row["override"]:
            row["excluded"] = f"distant territory (> {MAX_PART_GAP_KM} km), no hand-written scope"
        elif name in DISPUTED:
            row["excluded"] = "disputed border changes the outline"
        else:
            row["excluded"] = ""
        rows.append(row)
    return pd.DataFrame(rows)


# --- familiarity ----------------------------------------------------------------------------

def _get_json(url: str, retries: int = 6) -> dict:
    """GET JSON, backing off on HTTP 429 (honours Retry-After)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == retries - 1:
                raise
            time.sleep(float(e.headers.get("Retry-After") or 2 ** (attempt + 1)))


def fetch_pageviews(names: list[str]) -> pd.DataFrame:
    """Daily English Wikipedia pageviews over the last PAGEVIEW_DAYS days, 50 articles per request.

    Redirects are followed to the canonical article; a missing or disambiguation page is an error.
    """
    asked = {n: WIKI_TITLES.get(n, n) for n in names}
    found = {}
    titles = list(dict.fromkeys(asked.values()))
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        q = urllib.parse.urlencode({"action": "query", "format": "json", "formatversion": 2,
                                    "redirects": 1, "prop": "pageviews|pageprops",
                                    "pvipdays": PAGEVIEW_DAYS, "ppprop": "disambiguation",
                                    "titles": "|".join(batch)})
        data = _get_json(f"https://en.wikipedia.org/w/api.php?{q}")["query"]
        final = {t: t for t in batch}
        for m in data.get("normalized", []) + data.get("redirects", []):
            for t, cur in final.items():
                if cur == m["from"]:
                    final[t] = m["to"]
        pages = {p["title"]: p for p in data["pages"]}
        for t, f in final.items():
            p = pages.get(f, {})
            if p.get("missing") or "disambiguation" in p.get("pageprops", {}) or "pageviews" not in p:
                raise ValueError(f"Wikipedia title '{t}' -> '{f}' is missing, a disambiguation page, "
                                 "or has no pageview data")
            daily = p["pageviews"]
            found[t] = {"wiki_title": f, "days": sum(v is not None for v in daily.values()),
                        "first_day": min(daily), "last_day": max(daily),
                        "pageviews": sum(v or 0 for v in daily.values())}
        time.sleep(1)
    return pd.DataFrame([{"name": n, **found[t]} for n, t in asked.items()])


# --- selection ------------------------------------------------------------------------------

def select(df: pd.DataFrame) -> pd.DataFrame:
    """Median splits on log pageviews and on mean complexity rank; PER_CELL per cell, farthest from both medians."""
    ok = df[df["excluded"] == ""].copy()
    ok["familiarity_pct"] = np.log10(ok["pageviews"]).rank(pct=True)
    ok["complexity_score"] = (ok["roughness"].rank(pct=True) + ok["concavity"].rank(pct=True)) / 2
    ok["complexity_pct"] = ok["complexity_score"].rank(pct=True)
    ok["familiarity"] = np.where(ok["familiarity_pct"] > 0.5, "popular", "niche")
    ok["shape"] = np.where(ok["complexity_pct"] > 0.5, "complex", "simple")
    ok["margin"] = np.minimum((ok["familiarity_pct"] - 0.5).abs(), (ok["complexity_pct"] - 0.5).abs())
    picks = []
    for fam, shp in CELLS:
        cell = ok[(ok["familiarity"] == fam) & (ok["shape"] == shp)]
        picks.append(cell.sort_values("margin", ascending=False).head(PER_CELL))
    chosen = pd.concat(picks)
    df = df.merge(ok[["name", "familiarity_pct", "complexity_score", "complexity_pct",
                      "familiarity", "shape", "margin"]], on="name", how="left")
    df["selected"] = df["name"].isin(chosen["name"])
    return df


def default_scope(row) -> str:
    """Prompt sentence matching what the reference keeps (D-007)."""
    if row["raw_parts"] == 1:
        return "the whole country"
    if row["parts"] == 1:
        return "the main landmass only (leave out small islands)"
    return "the main landmasses only (leave out small islands)"


def write_countries(df: pd.DataFrame):
    overrides = {c["name"]: c for c in yaml.safe_load(OVERRIDES_FILE.read_text("utf-8"))["countries"]}
    out = []
    for fam, shp in CELLS:
        for _, r in df[df["selected"] & (df["familiarity"] == fam) & (df["shape"] == shp)].iterrows():
            spec = dict(overrides.get(r["name"], default_spec(r["name"])))
            spec.setdefault("scope", default_scope(r))
            spec.update({
                "familiarity": fam, "shape": shp,
                "wiki_title": r["wiki_title"], "pageviews": int(r["pageviews"]),
                "complexity_score": round(float(r["complexity_score"]), 3),
                "disc_iou": round(float(r["disc_iou"]), 3),
            })
            out.append(spec)
    header = ("# Generated by src/select_countries.py (D-009, D-021). Edit configs/scope_overrides.yaml\n"
              "# or the selection rules, then rerun; do not edit this file by hand.\n"
              "# Field meanings: see configs/scope_overrides.yaml and docs/DECISIONS.md.\n\n")
    COUNTRIES_FILE.write_text(header + yaml.safe_dump({"countries": out}, sort_keys=False, allow_unicode=True),
                              encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="query Wikipedia for pageviews")
    args = ap.parse_args()

    df = candidate_table()
    eligible = df.loc[df["excluded"] == "", "name"].tolist()
    if args.fetch or not PAGEVIEWS_FILE.exists():
        PAGEVIEWS_FILE.parent.mkdir(parents=True, exist_ok=True)
        fetch_pageviews(eligible).to_csv(PAGEVIEWS_FILE, index=False)
    pv = pd.read_csv(PAGEVIEWS_FILE)
    df = select(df.merge(pv, on="name", how="left"))
    df.to_csv(CANDIDATES_FILE, index=False, float_format="%.4f")
    write_countries(df)

    from plots import plot_country_selection
    plot_country_selection(df, FIGURE_FILE)

    print(df["excluded"].replace("", "eligible").value_counts().to_string(), "\n")
    sel = df[df["selected"]].sort_values(["familiarity", "shape", "pageviews"], ascending=[False, True, False])
    print(sel[["name", "familiarity", "shape", "pageviews", "complexity_score", "disc_iou", "parts"]]
          .to_string(index=False))
    print(f"\nWrote {COUNTRIES_FILE}, {CANDIDATES_FILE}, {FIGURE_FILE}")


if __name__ == "__main__":
    main()
