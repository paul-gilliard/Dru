"""Upload / stockage des photos de profil (athlète & coach)."""
from __future__ import annotations

import os
import re
import uuid

from flask import current_app
from werkzeug.utils import secure_filename

ALLOWED_AVATAR_EXT = {'.jpg', '.jpeg', '.png', '.webp'}
MAX_AVATAR_BYTES = 2 * 1024 * 1024


def avatar_storage_dir() -> str:
    preferred = os.environ.get('AVATAR_MEDIA_DIR')
    candidates = [
        preferred,
        os.path.join(current_app.instance_path if current_app else os.getcwd(), 'avatars'),
    ]
    for root in candidates:
        if not root:
            continue
        try:
            os.makedirs(root, exist_ok=True)
            return root
        except OSError:
            continue
    # Dernier recours : cwd
    root = os.path.join(os.getcwd(), 'avatars')
    os.makedirs(root, exist_ok=True)
    return root


def is_safe_avatar_filename(name: str) -> bool:
    if not name or '/' in name or '\\' in name or '..' in name:
        return False
    base, ext = os.path.splitext(name)
    return bool(base) and ext.lower() in ALLOWED_AVATAR_EXT and re.fullmatch(r'[a-f0-9]{32}', base) is not None


def _filename_from_stored_url(url: str | None) -> str | None:
    if not url:
        return None
    name = url.rstrip('/').split('/')[-1]
    return name if is_safe_avatar_filename(name) else None


def delete_avatar_file(url: str | None) -> None:
    name = _filename_from_stored_url(url)
    if not name:
        return
    path = os.path.join(avatar_storage_dir(), name)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def save_avatar_upload(file_storage) -> str:
    """Enregistre une image et retourne l'URL API relative."""
    if file_storage is None or not getattr(file_storage, 'filename', None):
        raise ValueError('Fichier manquant')
    filename = secure_filename(file_storage.filename or '')
    ext = os.path.splitext(filename)[1].lower()
    if ext == '.jpeg':
        ext = '.jpg'
    if ext not in ALLOWED_AVATAR_EXT:
        raise ValueError('Format accepté : JPG, PNG ou WebP')
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size <= 0:
        raise ValueError('Fichier vide')
    if size > MAX_AVATAR_BYTES:
        raise ValueError('Photo trop volumineuse (max 2 Mo)')
    stored = f'{uuid.uuid4().hex}{ext}'
    path = os.path.join(avatar_storage_dir(), stored)
    file_storage.save(path)
    return f'/api/media/avatars/{stored}'
