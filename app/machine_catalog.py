"""Catalogue machines : images originales scrapées + clés relatives."""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from flask import current_app

# Marques fermées (UI) — « Autre » = texte libre côté client.
MACHINE_BRANDS = [
    'Technogym',
    'Hammer Strength',
    'Panatta',
    'Atlantis',
    'Arsenal Strength',
    'Glutebuilder',
    'Etenon',
    'Matrix',
]

_SAFE_KEY_RE = re.compile(r'^[a-z0-9][a-z0-9._/-]*\.(jpg|jpeg|png|webp|avif|gif)$', re.IGNORECASE)


def _repo_root() -> Path:
    # Dru: app/... → parents[1] ; Dru-Mobile: backend/app/... → parents[2]
    here = Path(__file__).resolve()
    for parent in (here.parents[1], here.parents[2]):
        if (parent / 'data' / 'machine-catalog').exists():
            return parent
    return here.parents[1]


def catalog_json_path() -> Path:
    env = os.environ.get('MACHINE_CATALOG_JSON')
    if env:
        return Path(env)
    return _repo_root() / 'data' / 'machine-catalog' / 'catalog.json'


def machine_catalog_storage_dir() -> Path:
    """Dossier des originaux servis.

    Ordre : MACHINE_CATALOG_DIR → images du dépôt (prod git) → instance syncée.
    On évite de préférer un instance/ vide qui masquerait le catalogue versionné.
    """
    preferred = os.environ.get('MACHINE_CATALOG_DIR')
    try:
        instance = Path(current_app.instance_path) if current_app else None
    except RuntimeError:
        instance = None

    packaged = _repo_root() / 'data' / 'machine-catalog' / 'images'
    instance_dir = (instance / 'machine_catalog') if instance else (
        _repo_root() / 'backend' / 'instance' / 'machine_catalog'
    )

    def _has_files(root: Path) -> bool:
        if not root.is_dir():
            return False
        try:
            next(root.rglob('*'))
            return True
        except StopIteration:
            return False

    if preferred and _has_files(Path(preferred)):
        return Path(preferred)
    if _has_files(packaged):
        return packaged
    if _has_files(instance_dir):
        return instance_dir
    if preferred:
        Path(preferred).mkdir(parents=True, exist_ok=True)
        return Path(preferred)
    if packaged.is_dir() or not instance_dir.exists():
        packaged.mkdir(parents=True, exist_ok=True)
        return packaged
    instance_dir.mkdir(parents=True, exist_ok=True)
    return instance_dir


def is_safe_machine_image_key(key: str | None) -> bool:
    if not key or not isinstance(key, str):
        return False
    text = key.strip().replace('\\', '/')
    if not text or text.startswith('/') or '..' in text.split('/'):
        return False
    return bool(_SAFE_KEY_RE.match(text))


def normalize_machine_image_key(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().replace('\\', '/')
    if not text:
        return None
    if text.startswith('images/'):
        text = text[len('images/'):]
    if not is_safe_machine_image_key(text):
        raise ValueError('Clé image machine invalide')
    return text


def machine_image_file_path(key: str) -> Path | None:
    try:
        norm = normalize_machine_image_key(key)
    except ValueError:
        return None
    if not norm:
        return None
    root = machine_catalog_storage_dir().resolve()
    path = (root / norm).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path if path.is_file() else None


def machine_image_api_path(key: str | None) -> str | None:
    try:
        norm = normalize_machine_image_key(key)
    except ValueError:
        return None
    if not norm:
        return None
    return f'/api/media/machine-catalog/{norm}'


def machine_image_public_url(key: str | None) -> str | None:
    from app.exercise_media import public_absolute_url
    rel = machine_image_api_path(key)
    return public_absolute_url(rel) if rel else None


@lru_cache(maxsize=1)
def _load_catalog_raw() -> tuple[float | None, list[dict]]:
    path = catalog_json_path()
    if not path.is_file():
        return None, []
    mtime = path.stat().st_mtime
    with path.open(encoding='utf-8') as fh:
        data = json.load(fh)
    items = data.get('items') if isinstance(data, dict) else data
    if not isinstance(items, list):
        return mtime, []
    return mtime, items


def clear_catalog_cache() -> None:
    _load_catalog_raw.cache_clear()


def _item_key(item: dict) -> str | None:
    local = (item.get('local_path') or item.get('key') or '').strip().replace('\\', '/')
    if not local:
        return None
    try:
        return normalize_machine_image_key(local)
    except ValueError:
        return None


def list_catalog_items(*, brand: str | None = None, q: str | None = None) -> dict:
    """Liste les items dont le fichier local existe."""
    clear_catalog_cache()  # mtime-aware enough for admin updates; cheap vs IO
    _mtime, raw = _load_catalog_raw()
    brand_filter = (brand or '').strip().lower() or None
    needle = (q or '').strip().lower() or None
    root = machine_catalog_storage_dir()
    items_out = []
    brands_seen: set[str] = set()

    for item in raw:
        if not isinstance(item, dict):
            continue
        key = _item_key(item)
        if not key:
            continue
        if not (root / key).is_file():
            continue
        item_brand = (item.get('brand') or '').strip() or 'Autre'
        brands_seen.add(item_brand)
        if brand_filter and item_brand.lower() != brand_filter:
            continue
        name = (item.get('name') or '').strip() or key
        muscle = (item.get('muscle') or '').strip() or None
        if needle:
            hay = f'{name} {item_brand} {muscle or ""} {key}'.lower()
            if needle not in hay:
                continue
        items_out.append({
            'key': key,
            'name': name,
            'brand': item_brand,
            'muscle': muscle,
            'image_url': machine_image_public_url(key),
        })

    # Ordre marques : liste fermée d’abord, puis le reste alpha
    closed = [b for b in MACHINE_BRANDS if b in brands_seen]
    extra = sorted(b for b in brands_seen if b not in MACHINE_BRANDS)
    return {
        'brands': closed + extra,
        'items': items_out,
        'count': len(items_out),
    }
