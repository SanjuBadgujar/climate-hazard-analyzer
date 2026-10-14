import csv
import io
import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from . import service
from .config import settings
from .db import get_db, init_indexes
from .ingest import UpstreamError
from .schemas import AnalyzeParams

logging.basicConfig(level=logging.INFO)
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_indexes()
    yield


app = FastAPI(title="Climate Hazard Trend Analyzer", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_methods=["GET"],
    allow_headers=["*"],
    expose_headers=["X-Cache"],
)


def _run(params: AnalyzeParams):
    try:
        return service.get_analysis(get_db(), params)
    except ValueError as exc:                      # e.g. too much missing data
        raise HTTPException(422, str(exc)) from exc
    except UpstreamError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/geocode")
@limiter.limit("30/minute")
def geocode(request: Request, q: Annotated[str, Query(min_length=2, max_length=80)]):
    try:
        return {"results": service.geocode(q.strip())}
    except UpstreamError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/heatwave")
@limiter.limit(settings.analyze_rate_limit)
def heatwave(request: Request, response: Response, params: Annotated[AnalyzeParams, Query()]):
    result, hit = _run(params)
    response.headers["X-Cache"] = "HIT" if hit else "MISS"
    return result


@app.get("/api/heatwave/export.csv")
@limiter.limit(settings.analyze_rate_limit)
def export_csv(request: Request, params: Annotated[AnalyzeParams, Query()]):
    result, _ = _run(params)
    buf = io.StringIO()
    cols = ["year", "events", "heatwave_days", "max_duration_days", "mean_excess_c",
            "rolling5_days", "trend_days", "valid_days"]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    w.writerows({c: row[c] for c in cols} for row in result["yearly"])
    name = f"heatwave_{result['region']['region_key'].replace(',', '_')}_{params.start_year}-{params.end_year}.csv"
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
