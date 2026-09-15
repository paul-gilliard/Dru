"""YouTube OAuth (coach) — list own videos with thumbnails via Data API v3."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import jwt
from flask import current_app

YOUTUBE_SCOPE = 'https://www.googleapis.com/auth/youtube.readonly'
GOOGLE_AUTH = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN = 'https://oauth2.googleapis.com/token'
YT_API = 'https://www.googleapis.com/youtube/v3'


def _client_id() -> str:
    return (os.environ.get('GOOGLE_OAUTH_CLIENT_ID') or '').strip()


def _client_secret() -> str:
    return (os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET') or '').strip()


def youtube_oauth_configured() -> bool:
    return bool(_client_id() and _client_secret())


def youtube_redirect_uri() -> str:
    explicit = (os.environ.get('GOOGLE_OAUTH_REDIRECT_URI') or '').strip()
    if explicit:
        return explicit
    base = (os.environ.get('PUBLIC_BASE_URL') or '').rstrip('/')
    if not base:
        raise ValueError('PUBLIC_BASE_URL ou GOOGLE_OAUTH_REDIRECT_URI requis')
    return f'{base}/api/coach/youtube/callback'


def make_oauth_state(user_id: int) -> str:
    payload = {
        'uid': user_id,
        'purpose': 'youtube_oauth',
        'exp': datetime.now(timezone.utc) + timedelta(minutes=15),
    }
    return jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')


def parse_oauth_state(state: str) -> int:
    data = jwt.decode(state, current_app.config['SECRET_KEY'], algorithms=['HS256'])
    if data.get('purpose') != 'youtube_oauth':
        raise ValueError('state invalide')
    return int(data['uid'])


def build_authorize_url(user_id: int) -> str:
    if not youtube_oauth_configured():
        raise ValueError('YouTube OAuth non configuré (GOOGLE_OAUTH_CLIENT_ID / SECRET)')
    params = {
        'client_id': _client_id(),
        'redirect_uri': youtube_redirect_uri(),
        'response_type': 'code',
        'scope': YOUTUBE_SCOPE,
        'access_type': 'offline',
        'prompt': 'consent',
        'include_granted_scopes': 'true',
        'state': make_oauth_state(user_id),
    }
    return f'{GOOGLE_AUTH}?{urllib.parse.urlencode(params)}'


def _http_json(method: str, url: str, *, data: dict | None = None, headers: dict | None = None):
    body = None
    hdrs = dict(headers or {})
    if data is not None:
        body = urllib.parse.urlencode(data).encode('utf-8')
        hdrs.setdefault('Content-Type', 'application/x-www-form-urlencoded')
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode('utf-8')
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'HTTP {exc.code}: {detail[:300]}') from exc


def exchange_code_for_tokens(code: str) -> dict:
    return _http_json('POST', GOOGLE_TOKEN, data={
        'code': code,
        'client_id': _client_id(),
        'client_secret': _client_secret(),
        'redirect_uri': youtube_redirect_uri(),
        'grant_type': 'authorization_code',
    })


def refresh_access_token(refresh_token: str) -> dict:
    return _http_json('POST', GOOGLE_TOKEN, data={
        'client_id': _client_id(),
        'client_secret': _client_secret(),
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token',
    })


def fetch_channel_info(access_token: str) -> dict:
    url = (
        f'{YT_API}/channels?part=snippet,contentDetails&mine=true'
    )
    return _http_json('GET', url, headers={'Authorization': f'Bearer {access_token}'})


def list_my_videos(access_token: str, *, page_token: str | None = None, max_results: int = 25) -> dict:
    """Liste les uploads de la chaîne (y compris privés / non répertoriés pour le propriétaire)."""
    channels = fetch_channel_info(access_token)
    items = channels.get('items') or []
    if not items:
        return {'videos': [], 'next_page_token': None, 'channel_title': None}
    ch = items[0]
    uploads = (
        (ch.get('contentDetails') or {}).get('relatedPlaylists') or {}
    ).get('uploads')
    title = ((ch.get('snippet') or {}).get('title'))
    if not uploads:
        return {'videos': [], 'next_page_token': None, 'channel_title': title}

    qs = {
        'part': 'snippet,contentDetails,status',
        'playlistId': uploads,
        'maxResults': max(1, min(int(max_results), 50)),
    }
    if page_token:
        qs['pageToken'] = page_token
    pl = _http_json(
        'GET',
        f'{YT_API}/playlistItems?{urllib.parse.urlencode(qs)}',
        headers={'Authorization': f'Bearer {access_token}'},
    )
    videos = []
    for it in pl.get('items') or []:
        sn = it.get('snippet') or {}
        st = it.get('status') or {}
        thumbs = sn.get('thumbnails') or {}
        thumb = (
            (thumbs.get('medium') or {}).get('url')
            or (thumbs.get('high') or {}).get('url')
            or (thumbs.get('default') or {}).get('url')
        )
        vid = (sn.get('resourceId') or {}).get('videoId') or ''
        if not vid:
            continue
        privacy = st.get('privacyStatus') or sn.get('resourceId') and 'unknown'
        # status is on video resource; playlistItem may not have privacy — fetch from snippet if present
        videos.append({
            'id': vid,
            'title': sn.get('title') or vid,
            'description': (sn.get('description') or '')[:280],
            'thumbnail_url': thumb,
            'published_at': sn.get('publishedAt'),
            'privacy_status': privacy if isinstance(privacy, str) else None,
            'url': f'https://www.youtube.com/watch?v={vid}',
        })
    return {
        'videos': videos,
        'next_page_token': pl.get('nextPageToken'),
        'channel_title': title,
    }


def enrich_privacy(access_token: str, videos: list[dict]) -> list[dict]:
    """Complète privacyStatus via videos.list (batch)."""
    ids = [v['id'] for v in videos if v.get('id')]
    if not ids:
        return videos
    qs = urllib.parse.urlencode({
        'part': 'status,snippet',
        'id': ','.join(ids[:50]),
    })
    data = _http_json(
        'GET',
        f'{YT_API}/videos?{qs}',
        headers={'Authorization': f'Bearer {access_token}'},
    )
    by_id = {it['id']: it for it in (data.get('items') or [])}
    out = []
    for v in videos:
        it = by_id.get(v['id'])
        if it:
            v = dict(v)
            v['privacy_status'] = (it.get('status') or {}).get('privacyStatus')
            thumbs = ((it.get('snippet') or {}).get('thumbnails') or {})
            v['thumbnail_url'] = (
                (thumbs.get('medium') or {}).get('url')
                or v.get('thumbnail_url')
            )
        out.append(v)
    return out
