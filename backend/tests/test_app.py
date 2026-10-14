import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import ingest, processing
from app.main import app


def synthetic(y0=2000, y1=2019, seed=0, block=None):
    idx = pd.date_range(f"{y0}-01-01", f"{y1}-12-31")
    rng = np.random.default_rng(seed)
    doy = idx.dayofyear.to_numpy()
    s = pd.Series(25 + 10 * np.sin((doy - 100) / 365 * 2 * np.pi) + rng.normal(0, 1.5, len(idx)), index=idx)
    for start, days, bump in (block or []):
        s.loc[start:pd.Timestamp(start) + pd.Timedelta(days=days - 1)] += bump
    return s


def test_detects_injected_heatwave_and_ignores_two_day_spike():
    s = synthetic(block=[("2010-05-10", 6, 15), ("2012-05-10", 2, 15)])
    ev = processing.detect_events(s, processing.daily_thresholds(s, 95), 3)
    assert any(e["year"] == 2010 and e["duration_days"] >= 6 for e in ev)
    assert not any(e["start"] <= "2012-05-11" <= e["end"] and e["duration_days"] < 3 for e in ev)


def test_gap_breaks_run_and_bad_values_removed():
    s = synthetic(block=[("2010-05-10", 6, 15)])
    s.loc["2010-05-12":"2010-05-14"] = np.nan          # 3-day gap > interpolation limit
    s.loc["2005-01-01"] = 999                          # impossible value
    clean, q = processing.clean_series(s)
    assert q["invalid_values_removed"] == 1 and q["missing_days_after_cleaning"] >= 3
    thr = processing.daily_thresholds(clean, 95)
    ev = processing.detect_events(clean, thr, 3)
    assert not any(e["start"] <= "2010-05-12" <= e["end"] for e in ev)


def test_mann_kendall_detects_trend_and_flat():
    assert processing.mann_kendall(np.arange(20) + np.random.default_rng(1).normal(0, 1, 20))["trend"] == "increasing"
    assert processing.mann_kendall(np.ones(20))["trend"] == "no trend"


def test_api_end_to_end_with_cache(monkeypatch):
    calls = {"n": 0}

    def fake_fetch(lat, lon, start, end):
        calls["n"] += 1
        s = synthetic(start.year, end.year, block=[("2015-06-01", 5, 14)])
        return {"time": [d.strftime("%Y-%m-%d") for d in s.index], "temperature_2m_max": s.round(2).tolist()}

    monkeypatch.setattr(ingest, "fetch_tmax", fake_fetch)
    with TestClient(app) as client:
        q = "/api/heatwave?lat=18.52&lon=73.86&start_year=2000&end_year=2019"
        r1 = client.get(q)
        assert r1.status_code == 200 and r1.headers["X-Cache"] == "MISS"
        body = r1.json()
        assert len(body["yearly"]) == 20 and body["insights"]["headline"]
        r2 = client.get(q)
        assert r2.headers["X-Cache"] == "HIT" and calls["n"] == 1
        assert client.get(q.replace("/heatwave", "/heatwave/export.csv")).text.startswith("year,events")


@pytest.mark.parametrize("qs", [
    "lat=95&lon=10&start_year=1990&end_year=2020",
    "lat=10&lon=10&start_year=2000&end_year=2003",                 # span too short
    "lat=10&lon=10&start_year=1900&end_year=2020",
    "min_lat=0&max_lat=20&min_lon=0&max_lon=20&start_year=1990&end_year=2020",   # box too big
    "lat=10&start_year=1990&end_year=2020",
])
def test_input_validation(qs):
    with TestClient(app) as client:
        assert client.get("/api/heatwave?" + qs).status_code == 422


def test_absolute_floor_removes_cool_season_events():
    s = synthetic(block=[("2010-01-10", 5, 15)])           # warm spell in the cool season
    thr = processing.daily_thresholds(s, 95)
    assert processing.detect_events(s, thr, 3)
    assert not any(e["year"] == 2010 and e["start"].startswith("2010-01")
                   for e in processing.detect_events(s, thr, 3, min_tmax_c=40))
