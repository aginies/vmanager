"""
Module for caching VM metadata to reduce libvirt calls.
"""
import time
from typing import Any, Dict, Optional
from config import load_config

_cache: Dict[str, Dict[str, Any]] = {}
config = load_config()
TTL = config.get('CACHE_TTL', 1)  # Cache time-to-live in seconds

def get_from_cache(uuid: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves VM info from cache if available and not expired.
    """
    if uuid in _cache:
        entry = _cache[uuid]
        if time.time() - entry['timestamp'] < TTL:
            return entry['data']
    return None

def set_in_cache(uuid: str, data: Dict[str, Any]):
    """
    Stores VM info in the cache with a timestamp.
    """
    _cache[uuid] = {
        'data': data,
        'timestamp': time.time()
    }

def clear_cache():
    """
    Clears the entire VM cache.
    """
    _cache.clear()

def invalidate_cache(uuid: str):
    """
    Invalidates the cache for a specific VM.
    """
    if uuid in _cache:
        del _cache[uuid]
