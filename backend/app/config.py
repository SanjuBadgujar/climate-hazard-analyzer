import os
from dataclasses import dataclass, field


def _split(value: str) -> tuple[str, ...]:
    return tuple(v.strip() for v in value.split(",") if v.strip())


@dataclass(frozen=True)
class Settings:
    mongo_uri: str = os.getenv("MONGO_URI", "")
    mongo_db: str = os.getenv("MONGO_DB", "climate")
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: _split(os.getenv("CORS_ORIGINS", "http://localhost:5173, https://climate-hazard-analyzer-six.vercel.app",))
    )
    rate_limit: str = os.getenv("RATE_LIMIT", "60/minute")
    analyze_rate_limit: str = os.getenv("ANALYZE_RATE_LIMIT", "10/minute")
    analysis_ttl_days: int = int(os.getenv("ANALYSIS_TTL_DAYS", "30"))
    # Open-Meteo (free, no API key). ERA5 reanalysis, 0.25 degree grid.
    archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    geocode_url: str = "https://geocoding-api.open-meteo.com/v1/search"
    http_timeout_s: float = 30.0
    grid_step_deg: float = 0.25
    # Bump when detection/trend logic changes so old cached analyses are ignored.
    algo_version: int = 1


settings = Settings()
