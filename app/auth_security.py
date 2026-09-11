"""Anti-abus auth : rate limit IP + honeypot + blocklist bots (sans Redis)."""
from __future__ import annotations

import re
import threading
import time
from collections import defaultdict, deque

from flask import request

# Fenêtres glissantes en mémoire (ok pour 1 worker Gunicorn ; à migrer Redis si multi-replicas).
_LOCK = threading.Lock()
_HITS: dict[str, deque[float]] = defaultdict(deque)

REGISTER_LIMIT = 5          # inscriptions / IP
REGISTER_WINDOW_SEC = 3600  # par heure
LOGIN_LIMIT = 30            # tentatives / IP
LOGIN_WINDOW_SEC = 600      # par 10 min

_BOT_NAME_RE = re.compile(
    r'(crawler|scrap(e|er)?|spider|bot\b|robot|selenium|puppeteer|headless|http.?client)',
    re.I,
)

# Champs honeypot : l'app mobile les envoie vides ; un bot API les remplit souvent.
_HONEYPOT_KEYS = ('website', 'company', 'url', 'hp_field', 'fax')


def client_ip() -> str:
    forwarded = (request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
    if forwarded:
        return forwarded
    return request.remote_addr or 'unknown'


def _prune(bucket: deque[float], window_sec: int, now: float) -> None:
    while bucket and now - bucket[0] > window_sec:
        bucket.popleft()


def rate_limited(action: str, *, limit: int, window_sec: int) -> bool:
    """True si la limite est dépassée (et n'enregistre pas le hit)."""
    key = f'{action}:{client_ip()}'
    now = time.time()
    with _LOCK:
        bucket = _HITS[key]
        _prune(bucket, window_sec, now)
        return len(bucket) >= limit


def hit(action: str) -> None:
    key = f'{action}:{client_ip()}'
    now = time.time()
    with _LOCK:
        _HITS[key].append(now)


def honeypot_triggered(data: dict | None) -> bool:
    if not data:
        return False
    for key in _HONEYPOT_KEYS:
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return True
        if val not in (None, '', 0, False):
            if key in data and val:
                return True
    return False


def looks_like_bot_identity(email: str, display_name: str) -> bool:
    local = (email or '').split('@')[0]
    blob = f'{local} {display_name or ""}'
    return bool(_BOT_NAME_RE.search(blob))
