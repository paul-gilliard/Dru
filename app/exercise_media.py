"""Helpers médias exercices : YouTube, upload GIF, résolution par nom."""
from __future__ import annotations

import os
import re
import uuid
from urllib.parse import urlparse

from flask import current_app, request
from werkzeug.utils import secure_filename

YOUTUBE_RE = re.compile(
    r'^(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)[\w\-]{6,}',
    re.IGNORECASE,
)
ALLOWED_GIF_EXT = {'.gif', '.webp'}
MAX_GIF_BYTES = 3 * 1024 * 1024


def normalize_youtube_url(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if not YOUTUBE_RE.match(text):
        raise ValueError('URL YouTube invalide')
    if not text.startswith('http'):
        text = 'https://' + text
    return text[:512]


def media_storage_dir() -> str:
    preferred = os.environ.get('EXERCISE_MEDIA_DIR')
    candidates = [
        preferred,
        os.path.join(current_app.instance_path if current_app else os.getcwd(), 'exercise_media'),
    ]
    for root in candidates:
        if not root:
            continue
        try:
            os.makedirs(root, exist_ok=True)
            return root
        except OSError:
            continue
    root = os.path.join(os.getcwd(), 'exercise_media')
    os.makedirs(root, exist_ok=True)
    return root


def save_gif_upload(file_storage) -> str:
    """Enregistre un GIF/WebP et retourne l'URL API relative."""
    if file_storage is None or not getattr(file_storage, 'filename', None):
        raise ValueError('Fichier manquant')
    filename = secure_filename(file_storage.filename or '')
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_GIF_EXT:
        raise ValueError('Format accepté : .gif ou .webp')
    # Size check (best-effort)
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > MAX_GIF_BYTES:
        raise ValueError('Fichier trop volumineux (max 3 Mo)')
    stored = f'{uuid.uuid4().hex}{ext}'
    path = os.path.join(media_storage_dir(), stored)
    file_storage.save(path)
    return f'/api/media/exercises/{stored}'


def is_safe_media_filename(name: str) -> bool:
    if not name or '/' in name or '\\' in name or '..' in name:
        return False
    base, ext = os.path.splitext(name)
    return bool(base) and ext.lower() in ALLOWED_GIF_EXT and re.fullmatch(r'[a-f0-9]{32}', base) is not None


def public_absolute_url(path_or_url: str | None) -> str | None:
    if not path_or_url:
        return None
    if path_or_url.startswith('http://') or path_or_url.startswith('https://'):
        return path_or_url
    base = (os.environ.get('PUBLIC_BASE_URL') or request.url_root.rstrip('/')).rstrip('/')
    if path_or_url.startswith('/'):
        return f'{base}{path_or_url}'
    return f'{base}/{path_or_url}'


def media_dict_from_exercise(ex) -> dict:
    return {
        'id': ex.id,
        'name': ex.name,
        'muscle_group': ex.muscle_group,
        'animation_slug': ex.animation_slug,
        'youtube_url': ex.youtube_url,
        'custom_gif_url': public_absolute_url(ex.custom_gif_url) if ex.custom_gif_url else None,
        'media_status': ex.media_status or 'none',
        'has_media': bool(ex.animation_slug or ex.youtube_url or ex.custom_gif_url),
        'is_personal': ex.owner_id is not None,
    }


def media_dict_from_slug(name: str, slug: str) -> dict:
    return {
        'name': name,
        'animation_slug': slug,
        'youtube_url': None,
        'custom_gif_url': None,
        'media_status': 'approved',
        'has_media': True,
        'is_personal': False,
    }


def empty_media_dict(name: str) -> dict:
    return {
        'name': name,
        'animation_slug': None,
        'youtube_url': None,
        'custom_gif_url': None,
        'media_status': 'none',
        'has_media': False,
    }
