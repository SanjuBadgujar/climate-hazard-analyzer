"""Safe ingestion of daily Tmax from Open-Meteo (ERA5) with MongoDB caching.

Design notes
- Coordinates are snapped to the 0.25 deg ERA5 grid -> nearby clicks share one cache entry
  and callers cannot create unlimited distinct cache keys.
- Only years missing from the DB are fetched; one lock per grid cell stops duplicate
  upstream calls when several users hit the same new region at once.
- The upstream URL is fixed; user input only ever becomes validated numeric query params.
"""
import logging
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timezone

import httpx
import pandas as pd

from .config import settings

log = logging.getLogger(__name__)


class UpstreamError(RuntimeError):
    """Raised when the weather API fails or returns something unusable."""


def snap(value: float) -> float:
    step = settings.grid_step_deg
    return round(round(value / step) * step, 4)


def region_key(lat: float, lon: float) -> str:
    return f"{snap(lat):.2f},{snap(lon):.2f}"


_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)


def fetch_tmax(lat: float, lon: float, start: date, end: date) -> dict:
    """Return {"time": [...], "temperature_2m_max": [...]} from Open-Meteo. Retries 429/5xx."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": "temperature_2m_max",
        "temperature_unit": "celsius",   # explicit units, never rely on defaults
        "timezone": "UTC",
        "models": "era5",                # single homogeneous reanalysis (no model blending)
    }
    last_err = None
    for attempt in range(3):
        try:
            with httpx.Client(timeout=settings.http_timeout_s) as client:
                resp = client.get(settings.archive_url, params=params)
            if resp.status_code in (429, 500, 502, 503, 504):
                last_err = f"upstream status {resp.status_code}"
                time.sleep(2**attempt)
                continue
            resp.raise_for_status()
            daily = resp.json().get("daily") or {}
            if "time" not in daily or "temperature_2m_max" not in daily:
                raise UpstreamError("Unexpected response shape from weather API")
            if len(daily["time"]) != len(daily["temperature_2m_max"]):
                raise UpstreamError("Mismatched arrays from weather API")
            return daily
        except httpx.HTTPError as exc:
            last_err = str(exc)
            time.sleep(2**attempt)
    raise UpstreamError(f"Weather API unavailable: {last_err}")


def _years_in_db(db, key: str, y0: int, y1: int) -> set[int]:
    cur = db.raw_daily.find({"region_key": key, "year": {"$gte": y0, "$lte": y1}}, {"year": 1})
    return {d["year"] for d in cur}


def ensure_data(db, lat: float, lon: float, y0: int, y1: int) -> str:
    """Make sure daily data for [y0, y1] is in MongoDB; fetch only what is missing."""
    key = region_key(lat, lon)
    wanted = set(range(y0, y1 + 1))
    if not (wanted - _years_in_db(db, key, y0, y1)):
        return key
    with _locks[key]:
        missing = sorted(wanted - _years_in_db(db, key, y0, y1))  # re-check inside the lock
        if not missing:
            return key
        glat, glon = snap(lat), snap(lon)
        log.info("Fetching %s years %s-%s from Open-Meteo", key, missing[0], missing[-1])
        daily = fetch_tmax(glat, glon, date(missing[0], 1, 1), date(missing[-1], 12, 31))
        by_year: dict[int, tuple[list, list]] = defaultdict(lambda: ([], []))
        for t, v in zip(daily["time"], daily["temperature_2m_max"]):
            dates, vals = by_year[int(t[:4])]
            dates.append(t)
            vals.append(v)  # may be None (gap) - kept as null, handled in processing
        now = datetime.now(timezone.utc)
        for year in missing:
            if year not in by_year:
                continue
            dates, vals = by_year[year]
            db.raw_daily.update_one(
                {"region_key": key, "year": year},
                {"$set": {"region_key": key, "year": year, "lat": glat, "lon": glon, "dates": dates,
                          "tmax": vals, "source": "open-meteo-era5", "fetched_at": now}},
                upsert=True,
            )
    return key


def load_series(db, key: str, y0: int, y1: int) -> pd.Series:
    """Read stored daily Tmax back from MongoDB as a date-indexed float Series (gaps -> NaN)."""
    docs = db.raw_daily.find({"region_key": key, "year": {"$gte": y0, "$lte": y1}}).sort("year", 1)
    idx, vals = [], []
    for d in docs:
        idx.extend(d["dates"])
        vals.extend(d["tmax"])
    if not idx:
        raise UpstreamError("No data stored for this region")
    s = pd.Series(pd.to_numeric(pd.Series(vals), errors="coerce").to_numpy(dtype=float),
                  index=pd.to_datetime(idx))
    return s[~s.index.duplicated(keep="last")].sort_index()
