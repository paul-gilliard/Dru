"""Installe les GIF machines Farmness (dessins originaux) dans la banque commune.

Assets sous static/farmness_machine_guides/*.gif — illustrations originales
(style dessin), sans logos de marques. Les alias FR (Hammer, Technogym…)
pointent vers ces mouvements génériques.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from app import db
from app.exercise_media import media_storage_dir
from app.models import Exercise


PACK_DIR = Path(__file__).resolve().parents[1] / 'static' / 'farmness_machine_guides'
MANIFEST = PACK_DIR / 'manifest.json'


def _gif_filename(slug: str) -> str:
    digest = hashlib.md5(f'farmness-machine-{slug}'.encode('utf-8')).hexdigest()
    return f'{digest}.gif'


def install_farmness_machine_guides(*, force: bool = False) -> int:
    """Copie les GIF + upsert exercices communs. Retourne le nombre touché."""
    if not MANIFEST.is_file():
        print('⚠️ farmness_machine_guides manifest missing')
        return 0
    try:
        items = json.loads(MANIFEST.read_text(encoding='utf-8'))
    except Exception as e:
        print(f'⚠️ farmness_machine_guides manifest unreadable: {e}')
        return 0
    if not isinstance(items, list):
        return 0

    dest_dir = media_storage_dir()
    touched = 0
    for item in items:
        slug = (item.get('slug') or '').strip()
        name = (item.get('name') or '').strip()
        muscle = (item.get('muscle_group') or '').strip() or None
        if not slug or not name:
            continue
        src = PACK_DIR / f'{slug}.gif'
        if not src.is_file():
            print(f'⚠️ missing gif {src.name}')
            continue
        stored = _gif_filename(slug)
        dest = os.path.join(dest_dir, stored)
        if force or not os.path.isfile(dest) or os.path.getsize(dest) != src.stat().st_size:
            shutil.copy2(src, dest)

        rel_url = f'/api/media/exercises/{stored}'
        names = [name] + [a.strip() for a in (item.get('aliases') or []) if str(a).strip()]
        # Déduplique en préservant l’ordre
        seen = set()
        ordered = []
        for n in names:
            key = n.casefold()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(n)

        for n in ordered:
            # `Exercise.name` est unique globalement (pas par owner).
            ex = Exercise.query.filter_by(name=n).first()
            if ex is None:
                ex = Exercise(
                    name=n[:192],
                    muscle_group=(muscle or 'AUTRE')[:64],
                    owner_id=None,
                )
                db.session.add(ex)
            # Préférer notre GIF machine si pas déjà un custom coach
            if force or not ex.custom_gif_url or ex.custom_gif_url.endswith(stored):
                ex.custom_gif_url = rel_url
            if muscle and (not ex.muscle_group or ex.muscle_group == 'AUTRE'):
                ex.muscle_group = muscle[:64]
            if not ex.animation_slug:
                from app.exercise_animation_map import slug_for_exercise_name
                suggested = slug_for_exercise_name(n)
                if suggested:
                    ex.animation_slug = suggested
            if ex.media_status in (None, '', 'none'):
                ex.media_status = 'approved'
            touched += 1

    if touched:
        db.session.commit()
        print(f'✓ farmness machine guides installed ({touched} exercise rows)')
    return touched
