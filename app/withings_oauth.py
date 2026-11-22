"""Withings Public API — OAuth2 + poids / pas / sommeil → journal."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any

import jwt
from flask import current_app

WITHINGS_AUTH = 'https://account.withings.com/oauth2_user/authorize2'
WITHINGS_TOKEN = 'https://wbsapi.withings.net/v2/oauth2'
WITHINGS_MEASURE = 'https://wbsapi.withings.net/measure'
WITHINGS_MEASURE_V2 = 'https://wbsapi.withings.net/v2/measure'
WITHINGS_SLEEP = 'https://wbsapi.withings.net/v2/sleep'

# user.metrics = poids ; user.activity = pas ; user.sleepevents = sommeil
WITHINGS_SCOPES = 'user.info,user.metrics,user.activity,user.sleepevents'
MEASTYPE_WEIGHT = 1


def _client_id() -> str:
    return (os.environ.get('WITHINGS_CLIENT_ID') or '').strip()


def _client_secret() -> str:
    return (os.environ.get('WITHINGS_CLIENT_SECRET') or '').strip()


def withings_oauth_configured() -> bool:
    return bool(_client_id() and _client_secret())


def withings_redirect_uri() -> str:
    explicit = (os.environ.get('WITHINGS_REDIRECT_URI') or '').strip()
    if explicit:
        return explicit
    base = (os.environ.get('PUBLIC_BASE_URL') or '').rstrip('/')
    if not base:
        raise ValueError('Connexion Withings indisponible. Contacte le support.')
    return f'{base}/api/me/withings/callback'


def make_oauth_state(user_id: int) -> str:
    payload = {
        'uid': user_id,
        'purpose': 'withings_oauth',
        'exp': datetime.now(timezone.utc) + timedelta(minutes=15),
    }
    return jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')


def parse_oauth_state(state: str) -> int:
    data = jwt.decode(state, current_app.config['SECRET_KEY'], algorithms=['HS256'])
    if data.get('purpose') != 'withings_oauth':
        raise ValueError('state invalide')
    return int(data['uid'])


def build_authorize_url(user_id: int) -> str:
    if not withings_oauth_configured():
        raise ValueError('Connexion Withings indisponible pour le moment.')
    params = {
        'response_type': 'code',
        'client_id': _client_id(),
        'redirect_uri': withings_redirect_uri(),
        'scope': WITHINGS_SCOPES,
        'state': make_oauth_state(user_id),
    }
    return f'{WITHINGS_AUTH}?{urllib.parse.urlencode(params)}'


def _http_form(url: str, data: dict, *, headers: dict | None = None) -> dict:
    body = urllib.parse.urlencode({k: v for k, v in data.items() if v is not None}).encode('utf-8')
    hdrs = {'Content-Type': 'application/x-www-form-urlencoded', **(headers or {})}
    req = urllib.request.Request(url, data=body, headers=hdrs, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode('utf-8')
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'HTTP {exc.code}: {detail[:400]}') from exc


def _unwrap(payload: dict) -> dict:
    status = payload.get('status')
    if status not in (0, 100, None):
        raise RuntimeError(f'Withings status {status}: {payload}')
    return payload.get('body') or {}


def exchange_code_for_tokens(code: str) -> dict:
    body = _unwrap(_http_form(WITHINGS_TOKEN, {
        'action': 'requesttoken',
        'client_id': _client_id(),
        'client_secret': _client_secret(),
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': withings_redirect_uri(),
    }))
    return body


def refresh_access_token(refresh_token: str) -> dict:
    body = _unwrap(_http_form(WITHINGS_TOKEN, {
        'action': 'requesttoken',
        'client_id': _client_id(),
        'client_secret': _client_secret(),
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
    }))
    return body


def _auth_headers(access_token: str) -> dict:
    return {'Authorization': f'Bearer {access_token}'}


def _decode_measure(value: float | int, unit: int) -> float:
    return float(value) * (10 ** int(unit))


def _day_key_from_unix(ts: int, tz_name: str | None) -> str:
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name) if tz_name else timezone.utc
    except Exception:
        tz = timezone.utc
    return datetime.fromtimestamp(int(ts), tz=tz).date().isoformat()


def fetch_weights_by_day(
    access_token: str,
    *,
    start: date,
    end: date,
) -> dict[str, float]:
    """Dernier poids (kg) du jour → map YYYY-MM-DD → kg."""
    start_ts = int(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    end_ts = int(datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).timestamp()) - 1
    offset = 0
    by_day: dict[str, tuple[int, float]] = {}
    tz_name = None
    while True:
        body = _unwrap(_http_form(
            WITHINGS_MEASURE,
            {
                'action': 'getmeas',
                'meastypes': str(MEASTYPE_WEIGHT),
                'category': 1,
                'startdate': start_ts,
                'enddate': end_ts,
                'offset': offset,
            },
            headers=_auth_headers(access_token),
        ))
        tz_name = body.get('timezone') or tz_name
        for grp in body.get('measuregrps') or []:
            grp_date = int(grp.get('date') or 0)
            if not grp_date:
                continue
            day = _day_key_from_unix(grp_date, tz_name)
            for m in grp.get('measures') or []:
                if int(m.get('type') or 0) != MEASTYPE_WEIGHT:
                    continue
                kg = round(_decode_measure(m.get('value'), m.get('unit') or 0), 2)
                prev = by_day.get(day)
                if prev is None or grp_date >= prev[0]:
                    by_day[day] = (grp_date, kg)
        if int(body.get('more') or 0) != 1:
            break
        offset = int(body.get('offset') or 0)
        if offset <= 0:
            break
    return {day: kg for day, (_ts, kg) in by_day.items()}


def fetch_steps_by_day(
    access_token: str,
    *,
    start: date,
    end: date,
) -> dict[str, int]:
    body = _unwrap(_http_form(
        WITHINGS_MEASURE_V2,
        {
            'action': 'getactivity',
            'startdateymd': start.isoformat(),
            'enddateymd': end.isoformat(),
            'data_fields': 'steps',
        },
        headers=_auth_headers(access_token),
    ))
    out: dict[str, int] = {}
    for act in body.get('activities') or []:
        day = act.get('date')
        steps = act.get('steps')
        if day and steps is not None:
            try:
                n = int(steps)
            except (TypeError, ValueError):
                continue
            if n > 0:
                out[str(day)] = n
    return out


def fetch_sleep_hours_by_day(
    access_token: str,
    *,
    start: date,
    end: date,
) -> dict[str, float]:
    """Heures de sommeil par date de réveil (date Withings)."""
    body = _unwrap(_http_form(
        WITHINGS_SLEEP,
        {
            'action': 'getsummary',
            'startdateymd': start.isoformat(),
            'enddateymd': end.isoformat(),
            'data_fields': 'total_sleep_time,asleepduration,deepsleepduration,lightsleepduration,remsleepduration',
        },
        headers=_auth_headers(access_token),
    ))
    out: dict[str, float] = {}
    for series in body.get('series') or []:
        day = series.get('date')
        data = series.get('data') or {}
        seconds = data.get('total_sleep_time')
        if seconds is None:
            seconds = data.get('asleepduration')
        if seconds is None:
            parts = [
                data.get('deepsleepduration'),
                data.get('lightsleepduration'),
                data.get('remsleepduration'),
            ]
            if any(p is not None for p in parts):
                seconds = sum(int(p or 0) for p in parts)
        if not day or seconds is None:
            continue
        try:
            hours = round(float(seconds) / 3600.0, 1)
        except (TypeError, ValueError):
            continue
        if hours > 0:
            out[str(day)] = hours
    return out


def build_journal_snapshots(
    access_token: str,
    *,
    start: date,
    end: date,
    prefs: dict[str, bool],
) -> dict[str, dict[str, Any]]:
    """Map date ISO → champs journal à importer (selon prefs)."""
    want_weight = bool(prefs.get('weight'))
    want_steps = bool(prefs.get('steps'))
    want_sleep = bool(prefs.get('sleep_hours'))

    weights = fetch_weights_by_day(access_token, start=start, end=end) if want_weight else {}
    steps = fetch_steps_by_day(access_token, start=start, end=end) if want_steps else {}
    sleep = fetch_sleep_hours_by_day(access_token, start=start, end=end) if want_sleep else {}

    days = set(weights) | set(steps) | set(sleep)
    out: dict[str, dict[str, Any]] = {}
    for day in sorted(days):
        entry: dict[str, Any] = {}
        if day in weights:
            entry['weight'] = weights[day]
        if day in steps:
            entry['steps'] = steps[day]
        if day in sleep:
            entry['sleep_hours'] = sleep[day]
        if entry:
            out[day] = entry
    return out
