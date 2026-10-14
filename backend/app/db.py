"""MongoDB access. Falls back to an in-memory mongomock DB when MONGO_URI is empty."""
import logging

from pymongo import MongoClient

from .config import settings

log = logging.getLogger(__name__)
_client = None


def get_db():
    global _client
    if _client is None:
        if settings.mongo_uri:
            _client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000, tz_aware=True)
        else:
            import mongomock

            log.warning("MONGO_URI not set -> using in-memory mongomock (data lost on restart)")
            _client = mongomock.MongoClient()
    return _client[settings.mongo_db]


def init_indexes() -> None:
    db = get_db()
    # raw_daily: one document per (grid cell, year) holding that year's daily Tmax array
    db.raw_daily.create_index([("region_key", 1), ("year", 1)], unique=True)
    # analysis: computed hazard summaries, expire automatically
    db.analysis.create_index("cache_key", unique=True)
    try:
        db.analysis.create_index("created_at", expireAfterSeconds=settings.analysis_ttl_days * 86400)
    except Exception:  # mongomock may not support TTL
        log.debug("TTL index not created")
