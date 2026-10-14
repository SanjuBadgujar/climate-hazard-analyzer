"""Orchestrates: cache lookup -> ingest (if needed) -> read from DB -> analyse -> cache."""
from datetime import datetime, timezone
import hashlib
from functools import lru_cache

import httpx
import pandas as pd

from . import ingest, processing
from .config import settings
from .schemas import AnalyzeParams


def _cache_key(p: AnalyzeParams, rkey: str) -> str:
    raw = f"{p.hazard}|{rkey}|{p.start_year}|{p.end_year}|{p.percentile}|{p.min_days}|{p.min_tmax_c}|v{settings.algo_version}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get_analysis(db, p: AnalyzeParams) -> tuple[dict, bool]:
    """Returns (result, cache_hit)."""
    rkey = ingest.region_key(p.lat, p.lon)
    ckey = _cache_key(p, rkey)
    hit = db.analysis.find_one({"cache_key": ckey}, {"_id": 0, "result": 1})
    if hit:
        return hit["result"], True

    ingest.ensure_data(db, p.lat, p.lon, p.start_year, p.end_year)
    series = ingest.load_series(db, rkey, p.start_year, p.end_year)
    body = processing.analyze(series, p.start_year, p.end_year, p.percentile, p.min_days, p.min_tmax_c)
    glat, glon = ingest.snap(p.lat), ingest.snap(p.lon)
    result = {
        "hazard": p.hazard,
        "region": {"requested_lat": p.lat, "requested_lon": p.lon, "grid_lat": glat, "grid_lon": glon,
                   "region_key": rkey},
        "period": {"start_year": p.start_year, "end_year": p.end_year},
        "definition": {"variable": "temperature_2m_max (C)", "percentile": p.percentile,
                       "min_consecutive_days": p.min_days, "min_tmax_c": p.min_tmax_c, "threshold_window_days": 15,
                       "baseline": "selected period"},
        "source": "Open-Meteo Historical Weather API (ERA5 reanalysis)",
        **body,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    db.analysis.update_one({"cache_key": ckey},
                           {"$set": {"cache_key": ckey, "result": result,
                                     "created_at": datetime.now(timezone.utc)}},
                           upsert=True)
    return result, False


@lru_cache(maxsize=512)
def geocode(query: str) -> list[dict]:
    try:
        with httpx.Client(timeout=settings.http_timeout_s) as c:
            r = c.get(settings.geocode_url,
                      params={"name": query, "count": 6, "language": "en", "format": "json"})
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise ingest.UpstreamError(f"Geocoding unavailable: {exc}") from exc
    return [{"name": x.get("name"), "admin1": x.get("admin1"), "country": x.get("country"),
             "lat": x["latitude"], "lon": x["longitude"]} for x in r.json().get("results", [])]
