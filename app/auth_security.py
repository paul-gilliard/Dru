"""Anti-abus auth : rate limit IP + honeypot + blocklist bots (sans Redis)."""
from __future__ import annotations

import os
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
SEARCH_LIMIT = 40           # recherches athlètes / IP
SEARCH_WINDOW_SEC = 600

_BOT_NAME_RE = re.compile(
    r'(crawler|scrap(e|er)?|spider|bot\b|robot|selenium|puppeteer|headless|http.?client)',
    re.I,
)

# Champs honeypot : l'app mobile les envoie vides ; un bot API les remplit souvent.
_HONEYPOT_KEYS = ('website', 'company', 'url', 'hp_field', 'fax')


def trusted_proxy_count() -> int:
    """Nombre de proxies de confiance devant l'app (Railway = 1 par défaut en prod)."""
    raw = (os.environ.get('TRUSTED_PROXY_COUNT') or '').strip()
    if raw.isdigit():
        return max(0, int(raw))
    # Railway / reverse-proxy : X-Forwarded-For fiable si on prend la bonne entrée.
    if os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('RAILWAY_PUBLIC_DOMAIN'):
        return 1
    return 0


def client_ip() -> str:
    """IP client : ne fait confiance à X-Forwarded-For que si proxies configurés."""
    remote = (request.remote_addr or 'unknown').strip()
    hops = trusted_proxy_count()
    if hops <= 0:
        return remote or 'unknown'
    forwarded = (request.headers.get('X-Forwarded-For') or '').strip()
    if not forwarded:
        return remote or 'unknown'
    parts = [p.strip() for p in forwarded.split(',') if p.strip()]
    if not parts:
        return remote or 'unknown'
    # Avec N proxies de confiance, l'IP client est à -(N+1) depuis la fin
    # (dernier = proxy le plus proche). Fallback : première entrée.
    idx = max(0, len(parts) - hops - 1) if hops else 0
    # Convention courante : premier hop = client original derrière 1 proxy.
    if hops == 1 and len(parts) >= 1:
        return parts[0]
    return parts[idx] if idx < len(parts) else parts[0]


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
