"""Request validation. Everything user-controlled goes through here."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

MIN_YEAR = 1950          # ERA5 in Open-Meteo is reliable from 1950 on
MIN_SPAN_YEARS = 10      # percentiles + Mann-Kendall are meaningless on very short records
MAX_SPAN_YEARS = 40
MAX_BOX_DEG = 5.0


def last_full_year() -> int:
    return date.today().year - 1


class AnalyzeParams(BaseModel):
    hazard: Literal["heatwave"] = "heatwave"
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    # optional bounding box (min_lat,max_lat,min_lon,max_lon); centre point is analysed
    min_lat: float | None = Field(default=None, ge=-90, le=90)
    max_lat: float | None = Field(default=None, ge=-90, le=90)
    min_lon: float | None = Field(default=None, ge=-180, le=180)
    max_lon: float | None = Field(default=None, ge=-180, le=180)
    start_year: int = Field(default=1990, ge=MIN_YEAR)
    end_year: int = Field(default=2020)
    percentile: int = Field(default=95, ge=90, le=99)
    min_days: int = Field(default=3, ge=2, le=10)
    # optional absolute floor (C): a day counts only if Tmax is ALSO >= this value
    min_tmax_c: float | None = Field(default=None, ge=0, le=55)

    @model_validator(mode="after")
    def _check(self):
        box = [self.min_lat, self.max_lat, self.min_lon, self.max_lon]
        if any(v is not None for v in box):
            if any(v is None for v in box):
                raise ValueError("Provide all of min_lat, max_lat, min_lon, max_lon for a box")
            if self.min_lat >= self.max_lat or self.min_lon >= self.max_lon:
                raise ValueError("Box minimums must be smaller than maximums")
            if self.max_lat - self.min_lat > MAX_BOX_DEG or self.max_lon - self.min_lon > MAX_BOX_DEG:
                raise ValueError(f"Box too large (max {MAX_BOX_DEG} degrees per side)")
            self.lat = round((self.min_lat + self.max_lat) / 2, 4)
            self.lon = round((self.min_lon + self.max_lon) / 2, 4)
        if self.lat is None or self.lon is None:
            raise ValueError("Provide lat & lon, or a full bounding box")
        last = last_full_year()
        if self.end_year > last:
            raise ValueError(f"end_year cannot be after {last} (last complete year)")
        if self.end_year < self.start_year:
            raise ValueError("end_year must be >= start_year")
        span = self.end_year - self.start_year + 1
        if span < MIN_SPAN_YEARS or span > MAX_SPAN_YEARS:
            raise ValueError(f"Period must span {MIN_SPAN_YEARS}-{MAX_SPAN_YEARS} years")
        return self
