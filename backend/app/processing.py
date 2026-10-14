"""Pure functions: cleaning, heatwave detection, trends, honest insights. No I/O here."""
import math

import numpy as np
import pandas as pd
from scipy import stats

TMAX_MIN_C, TMAX_MAX_C = -60.0, 60.0   # physically implausible daily-max 2 m temperatures
MAX_INTERP_GAP = 2                       # fill gaps of <= 2 days; longer gaps stay missing
WINDOW_HALF_DAYS = 7                     # +-7 day window => 15 days x N years per percentile
MIN_POOL = 30                            # min samples to trust a percentile
MIN_VALID_FRACTION = 0.8

_LUT = np.zeros((13, 32), dtype=int)     # (month, day) -> slot 0..365 on a leap-year calendar
for _i, _d in enumerate(pd.date_range("2000-01-01", "2000-12-31")):
    _LUT[_d.month, _d.day] = _i


def _num(x, nd=2):
    if x is None:
        return None
    x = float(x)
    return None if (math.isnan(x) or math.isinf(x)) else round(x, nd)


# --------------------------------------------------------------------------- cleaning

def _interpolate_short_gaps(s: pd.Series) -> pd.Series:
    """Linear-interpolate only NaN runs of <= MAX_INTERP_GAP days (pandas' `limit` would
    partially fill longer runs, which we do not want)."""
    isna = s.isna()
    run_len = isna.groupby((isna != isna.shift()).cumsum()).transform("sum")
    filled = s.interpolate(limit_area="inside")
    return filled.mask(isna & (run_len > MAX_INTERP_GAP))

def clean_series(raw: pd.Series) -> tuple[pd.Series, dict]:
    s = raw.astype(float).sort_index()
    full = pd.date_range(s.index.min(), s.index.max(), freq="D")
    s = s.reindex(full)
    total = len(s)
    missing_raw = int(s.isna().sum())               # includes days absent from the response
    bad = (s < TMAX_MIN_C) | (s > TMAX_MAX_C)
    outliers = int(bad.sum())
    s = s.mask(bad)                                  # only *physical* impossibilities are removed:
    before = int(s.isna().sum())                     # real extreme heat is the signal, not noise
    s = _interpolate_short_gaps(s)
    filled = before - int(s.isna().sum())
    still_missing = int(s.isna().sum())
    quality = {
        "total_days": total,
        "missing_days_raw": missing_raw,
        "invalid_values_removed": outliers,
        "gaps_interpolated_days": filled,
        "missing_days_after_cleaning": still_missing,
        "valid_fraction": _num(1 - still_missing / total, 4),
        "notes": [
            "Units fixed to degrees Celsius at request time.",
            f"Values outside {TMAX_MIN_C:.0f}..{TMAX_MAX_C:.0f} C treated as invalid; statistical "
            "outliers are kept because extreme heat is exactly what is being measured.",
            f"Gaps up to {MAX_INTERP_GAP} days are linearly interpolated; longer gaps stay missing "
            "and cannot start or extend a heatwave.",
        ],
    }
    if 1 - still_missing / total < MIN_VALID_FRACTION:
        raise ValueError("Too much missing data for a reliable analysis of this region/period")
    return s, quality


# --------------------------------------------------------------------------- heatwaves
def daily_thresholds(s: pd.Series, pct: float, half_window: int = WINDOW_HALF_DAYS) -> pd.Series:
    """Percentile of Tmax for every calendar day, pooling +-half_window days across all years."""
    slots = _LUT[s.index.month, s.index.day]
    vals = s.to_numpy()
    by_slot = [vals[slots == i] for i in range(366)]
    thr = np.full(366, np.nan)
    for i in range(366):
        pool = np.concatenate([by_slot[(i + k) % 366] for k in range(-half_window, half_window + 1)])
        pool = pool[~np.isnan(pool)]
        if pool.size >= MIN_POOL:
            thr[i] = np.percentile(pool, pct)
    return pd.Series(thr[slots], index=s.index)


def detect_events(s: pd.Series, thr: pd.Series, min_days: int, min_tmax_c: float | None = None) -> list[dict]:
    """Runs of >= min_days consecutive days with Tmax strictly above the day's threshold.
    NaN compares False, so a missing day ends a run (conservative)."""
    hot = s > thr
    if min_tmax_c is not None:
        hot &= s >= min_tmax_c            # absolute floor removes 'hot for a monsoon day' events
    above = hot.to_numpy().astype(int)
    diff = np.diff(np.concatenate(([0], above, [0])))
    starts, ends = np.where(diff == 1)[0], np.where(diff == -1)[0]   # ends are exclusive
    events = []
    for a, b in zip(starts, ends):
        if b - a >= min_days:
            seg, t = s.iloc[a:b], thr.iloc[a:b]
            events.append({
                "start": seg.index[0].date().isoformat(),
                "end": seg.index[-1].date().isoformat(),
                "year": int(seg.index[0].year),           # assigned to the year it starts in
                "duration_days": int(b - a),
                "peak_tmax_c": _num(seg.max(), 1),
                "mean_excess_c": _num((seg - t).mean(), 2),
            })
    return events


def yearly_table(s: pd.Series, events: list[dict], y0: int, y1: int) -> pd.DataFrame:
    years = list(range(y0, y1 + 1))
    df = pd.DataFrame({"year": years}).set_index("year")
    ev = pd.DataFrame(events) if events else pd.DataFrame(
        columns=["year", "duration_days", "mean_excess_c"])
    g = ev.groupby("year")
    df["events"] = g.size().reindex(years).fillna(0).astype(int)
    df["heatwave_days"] = g["duration_days"].sum().reindex(years).fillna(0).astype(int)
    df["max_duration_days"] = g["duration_days"].max().reindex(years).fillna(0).astype(int)
    df["mean_excess_c"] = g["mean_excess_c"].mean().reindex(years)          # NaN if no event
    df["valid_days"] = s.groupby(s.index.year).apply(lambda x: int(x.notna().sum())).reindex(years).fillna(0).astype(int)
    df["rolling5_days"] = df["heatwave_days"].rolling(5, center=True, min_periods=3).mean()
    return df


# --------------------------------------------------------------------------- trends
def mann_kendall(y) -> dict:
    """Mann-Kendall trend test with tie correction + Theil-Sen slope (per time step)."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    i, j = np.triu_indices(n, k=1)
    s = float(np.sign(y[j] - y[i]).sum())
    _, counts = np.unique(y, return_counts=True)
    var = (n * (n - 1) * (2 * n + 5) - np.sum(counts * (counts - 1) * (2 * counts + 5))) / 18.0
    if var <= 0:
        return {"z": 0.0, "p_value": 1.0, "sens_slope": 0.0, "trend": "no trend"}
    z = (s - np.sign(s)) / math.sqrt(var)
    p = float(2 * (1 - stats.norm.cdf(abs(z))))
    sen = float(np.median((y[j] - y[i]) / (j - i)))
    trend = "no trend" if p >= 0.05 else ("increasing" if z > 0 else "decreasing")
    return {"z": _num(z, 3), "p_value": _num(p, 4), "sens_slope": _num(sen, 4), "trend": trend}


def trend_block(years: np.ndarray, y: np.ndarray) -> dict:
    lr = stats.linregress(years, y)
    mk = mann_kendall(y)
    return {
        "linear": {"slope_per_decade": _num(lr.slope * 10, 3), "intercept": float(lr.intercept),
                   "p_value": _num(lr.pvalue, 4), "r_squared": _num(lr.rvalue**2, 3)},
        "mann_kendall": {**mk, "sens_slope_per_decade": _num((mk["sens_slope"] or 0) * 10, 3)},
    }


# --------------------------------------------------------------------------- insights
def build_insights(df: pd.DataFrame, trends: dict, pct: int, min_days: int) -> dict:
    n = len(df)
    k = 10 if n >= 20 else n // 2
    early, late = df.iloc[:k], df.iloc[-k:]
    e, l = float(early["heatwave_days"].mean()), float(late["heatwave_days"].mean())
    lbl_e = f"{early.index[0]}-{early.index[-1]}"
    lbl_l = f"{late.index[0]}-{late.index[-1]}"
    mk = trends["heatwave_days"]["mann_kendall"]
    p = mk["p_value"]
    p_txt = "<0.001" if (p is not None and p < 0.001) else str(p)
    significant = p is not None and p < 0.05

    if e == 0 and l == 0:
        headline = "No heatwaves were detected under this definition in either period."
    elif e == 0:
        headline = (f"Heatwave days rose from 0 per year in {lbl_e} to {l:.1f} per year in {lbl_l} "
                    "(a % change is undefined from a zero baseline).")
    else:
        change = (l - e) / e * 100
        word = "increased" if change > 10 else "decreased" if change < -10 else "changed little"
        headline = (f"Heatwave days per year {word}: {e:.1f} in {lbl_e} vs {l:.1f} in {lbl_l} "
                    f"({change:+.0f}%).")
    verdict = (f"The long-term trend is statistically {mk['trend']} (Mann-Kendall p={p_txt})."
               if significant else
               f"The year-to-year trend is not statistically significant (Mann-Kendall p={p_txt}); "
               "the difference above could be natural variability.")
    details = [
        verdict,
        f"Linear trend: {trends['heatwave_days']['linear']['slope_per_decade']:+.2f} heatwave days per decade; "
        f"Theil-Sen: {mk['sens_slope_per_decade']:+.2f} per decade.",
        f"Total events: {int(df['events'].sum())}; longest: {int(df['max_duration_days'].max())} days.",
    ]
    caveats = [
        f"A heatwave = {min_days}+ consecutive days with Tmax above the local {pct}th percentile "
        "of that calendar day (+-7 day window), computed from the same period analysed. "
        "This guarantees ~5% exceedance by construction, so trends show change *within* the period.",
        "Data are ERA5 reanalysis on a ~25 km grid cell, not station records; a box is "
        "represented by its centre cell.",
        "Events are assigned to the year they start in; Southern-Hemisphere summer events that "
        "span New Year are counted once.",
    ]
    return {"headline": headline, "details": details, "caveats": caveats,
            "significant": bool(significant)}


# --------------------------------------------------------------------------- orchestration
def analyze(raw: pd.Series, y0: int, y1: int, pct: int, min_days: int, min_tmax_c: float | None = None) -> dict:
    s, quality = clean_series(raw)
    thr = daily_thresholds(s, pct)
    events = detect_events(s, thr, min_days, min_tmax_c)
    df = yearly_table(s, events, y0, y1)
    yrs = df.index.to_numpy(dtype=float)
    trends = {"heatwave_days": trend_block(yrs, df["heatwave_days"].to_numpy(dtype=float)),
              "events": trend_block(yrs, df["events"].to_numpy(dtype=float))}
    exact = stats.linregress(yrs, df["heatwave_days"].to_numpy(dtype=float))  # for the plotted trend line
    df["trend_days"] = exact.intercept + exact.slope * yrs
    trends["heatwave_days"]["linear"].pop("intercept", None)
    trends["events"]["linear"].pop("intercept", None)

    yearly = [{
        "year": int(y), "events": int(r.events), "heatwave_days": int(r.heatwave_days),
        "max_duration_days": int(r.max_duration_days), "mean_excess_c": _num(r.mean_excess_c),
        "valid_days": int(r.valid_days), "rolling5_days": _num(r.rolling5_days),
        "trend_days": _num(r.trend_days),
    } for y, r in df.iterrows()]
    return {
        "data_quality": quality,
        "threshold_summary": {"min_c": _num(np.nanmin(thr)), "max_c": _num(np.nanmax(thr)),
                              "mean_c": _num(np.nanmean(thr))},
        "yearly": yearly,
        "events": events[:1000],
        "trends": trends,
        "insights": build_insights(df, trends, pct, min_days),
    }
