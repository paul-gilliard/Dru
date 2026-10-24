"""Import de plans alimentaires depuis Excel / CSV / PDF / images via Claude.

Réutilise le stockage / extraction fichiers de program_import (jobs uuid).
"""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

from app import program_import as prog

CLAUDE_MODEL = os.environ.get(
    'ANTHROPIC_MEAL_IMPORT_MODEL',
    os.environ.get('ANTHROPIC_PROGRAM_IMPORT_MODEL', 'claude-sonnet-5-5'),
)

SYSTEM_PROMPT = """Tu es un expert nutrition sportive qui convertit des plans alimentaires / diètes
(Excel, CSV, PDF, photos ou captures d'écran) vers le format Farmness.

Règles:
- Extrais UNIQUEMENT le plan alimentaire (ignore musculation, journaux, métriques hors diète).
- Si plusieurs images sont fournies, elles forment UN SEUL plan découpé : lis-les dans l'ordre et fusionne.
- meal_number : 1 à 6 (petit-déj=1, déjeuner, collation, dîner…). Max 6 repas.
- quantity_g : quantité en grammes (nombre). Si "1 unité" / "2 oeufs", estime en grammes raisonnablement.
- label : nom du repas (Petit-déjeuner, Déjeuner…).
- time : HH:MM si visible, sinon null.
- name : nom d'aliment tel qu'écrit (ex: "Riz basmati cuit", "Blanc de poulet").
- brand : marque si indiquée, sinon null.
- kcal / proteins / lipids / carbs : pour 100g si lisibles (sinon null) — utiles pour créer un aliment perso.
- plan_name : titre du fichier/onglet ou "Plan alimentaire importé".
- meal_count : nombre de repas distincts (1–6).
- warnings : ambiguïtés.

Réponds UNIQUEMENT avec un JSON valide (pas de markdown) de forme:
{
  "plan_name": "string",
  "meal_count": 4,
  "meals": [
    {
      "meal_number": 1,
      "label": "string|null",
      "time": "HH:MM|null",
      "items": [
        {
          "name": "string",
          "quantity_g": 100,
          "brand": "string|null",
          "kcal": null,
          "proteins": null,
          "lipids": null,
          "carbs": null
        }
      ]
    }
  ],
  "warnings": ["string"]
}
"""


def create_upload_job(*, coach_id: int, files: list[tuple[str, bytes]] | None = None) -> dict:
    meta = prog.create_upload_job(coach_id=coach_id, files=files)
    meta['import_kind'] = 'meal'
    prog.save_job(meta)
    return meta


def load_job(job_id: str) -> dict | None:
    return prog.load_job(job_id)


def save_job(meta: dict) -> None:
    prog.save_job(meta)


def build_extract_payload(meta: dict, *, sheet: str | None, page: int | None) -> dict:
    return prog.build_extract_payload(meta, sheet=sheet, page=page)


def _fold(s: str) -> str:
    return prog._fold(s)


def _extract_json_object(raw: str) -> dict:
    return prog._extract_json_object(raw)


def _parse_quantity(raw) -> float | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, (int, float)):
        val = float(raw)
        return val if val > 0 else None
    text = str(raw).strip().lower().replace(',', '.')
    m = re.search(r'(\d+(?:\.\d+)?)', text)
    if not m:
        return None
    val = float(m.group(1))
    return val if val > 0 else None


def _parse_macro(raw) -> float | None:
    q = _parse_quantity(raw)
    if q is None:
        return None
    return round(q, 2)


def _parse_time(raw) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    m = re.fullmatch(r'(\d{1,2})\s*[:hH]\s*(\d{2})', text)
    if not m:
        m = re.fullmatch(r'(\d{1,2})\s*h', text, flags=re.I)
        if m:
            h = max(0, min(23, int(m.group(1))))
            return f'{h:02d}:00'
        return None
    h = max(0, min(23, int(m.group(1))))
    mi = max(0, min(59, int(m.group(2))))
    return f'{h:02d}:{mi:02d}'


def normalize_draft(raw: dict) -> dict:
    name = (raw.get('plan_name') or raw.get('program_name') or 'Plan alimentaire importé').strip()[:128]
    if not name:
        name = 'Plan alimentaire importé'
    try:
        meal_count = int(raw.get('meal_count') or 0)
    except (TypeError, ValueError):
        meal_count = 0

    meals_out = []
    for i, meal in enumerate(raw.get('meals') or []):
        if not isinstance(meal, dict):
            continue
        try:
            num = int(meal.get('meal_number') or (i + 1))
        except (TypeError, ValueError):
            num = i + 1
        num = max(1, min(6, num))
        label = (meal.get('label') or '').strip()[:100] or None
        time = _parse_time(meal.get('time'))
        items = []
        for it in meal.get('items') or []:
            if not isinstance(it, dict):
                continue
            iname = (it.get('name') or '').strip()[:192]
            if not iname:
                continue
            qty = _parse_quantity(it.get('quantity_g') if 'quantity_g' in it else it.get('quantity'))
            if qty is None:
                qty = 100.0
            items.append({
                'name': iname,
                'quantity_g': round(float(qty), 1),
                'brand': ((str(it['brand']).strip()[:100] or None) if it.get('brand') else None),
                'kcal': _parse_macro(it.get('kcal')),
                'proteins': _parse_macro(it.get('proteins')),
                'lipids': _parse_macro(it.get('lipids')),
                'carbs': _parse_macro(it.get('carbs')),
            })
        if items:
            meals_out.append({
                'meal_number': num,
                'label': label,
                'time': time,
                'items': items,
            })

    if not meal_count:
        meal_count = max((m['meal_number'] for m in meals_out), default=1)
    meal_count = max(1, min(6, meal_count))
    warnings = [str(w) for w in (raw.get('warnings') or []) if w][:20]
    return {
        'plan_name': name,
        'meal_count': meal_count,
        'meals': meals_out,
        'warnings': warnings,
    }


def call_claude_parse(*, extract: dict, hint: str | None, filename: str) -> dict:
    """Appelle Anthropic pour un plan alimentaire. Overridable en tests."""
    api_key = (os.environ.get('ANTHROPIC_API_KEY') or '').strip()
    if not api_key:
        raise RuntimeError("L'import intelligent est temporairement indisponible.")

    import anthropic

    user_bits: list[Any] = []
    coach_hint = (hint or '').strip()
    preamble = (
        f"Fichier source : {filename}\n"
        f"Consignes (optionnel) : {coach_hint or '(aucune)'}\n"
        "Extrais le plan alimentaire au format JSON demandé."
    )

    if extract['mode'] == 'images' and extract.get('images'):
        images = extract['images']
        user_bits.append({
            'type': 'text',
            'text': (
                f"{preamble}\n\n"
                f"{len(images)} image(s) fournie(s), dans l'ordre. "
                "Elles décrivent un seul et même plan alimentaire."
            ),
        })
        for idx, img in enumerate(images):
            user_bits.append({'type': 'text', 'text': f'Image {idx + 1}/{len(images)} :'})
            user_bits.append({
                'type': 'image',
                'source': {
                    'type': 'base64',
                    'media_type': img['media_type'],
                    'data': base64.standard_b64encode(img['bytes']).decode('ascii'),
                },
            })
    elif extract['mode'] == 'pdf' and extract.get('file_bytes'):
        b64 = base64.standard_b64encode(extract['file_bytes']).decode('ascii')
        user_bits.append({
            'type': 'document',
            'source': {
                'type': 'base64',
                'media_type': 'application/pdf',
                'data': b64,
            },
        })
        user_bits.append({'type': 'text', 'text': preamble})
    else:
        text = extract.get('text') or ''
        user_bits.append({
            'type': 'text',
            'text': f"{preamble}\n\n--- CONTENU ---\n{text}",
        })

    model = (os.environ.get('ANTHROPIC_MEAL_IMPORT_MODEL') or CLAUDE_MODEL).strip()
    client = anthropic.Anthropic(api_key=api_key)
    create_kwargs: dict[str, Any] = {
        'model': model,
        'max_tokens': 8192,
        'system': SYSTEM_PROMPT,
        'messages': [{'role': 'user', 'content': user_bits}],
    }
    if model.startswith('claude-sonnet-5') or model.startswith('claude-opus-5'):
        create_kwargs['output_config'] = {'effort': 'low'}
    try:
        msg = client.messages.create(**create_kwargs)
    except TypeError:
        create_kwargs.pop('output_config', None)
        msg = client.messages.create(**create_kwargs)
    parts = []
    for block in msg.content:
        if getattr(block, 'type', None) == 'text':
            parts.append(block.text)
    raw = _extract_json_object('\n'.join(parts))
    return normalize_draft(raw)


def build_match_items(draft: dict) -> list[dict]:
    """Une entrée unique par nom d'aliment source."""
    seen: dict[str, dict] = {}
    order: list[str] = []
    for mi, meal in enumerate(draft.get('meals') or []):
        for ii, item in enumerate(meal.get('items') or []):
            name = (item.get('name') or '').strip()
            if not name:
                continue
            key = _fold(name)
            if key not in seen:
                seen[key] = {
                    'key': f'food_{len(order)}',
                    'source_name': name,
                    'brand': item.get('brand'),
                    'suggested_macros': {
                        'kcal': item.get('kcal'),
                        'proteins': item.get('proteins'),
                        'lipids': item.get('lipids'),
                        'carbs': item.get('carbs'),
                    },
                    'occurrences': [],
                    'candidates': [],
                    'suggested': None,
                    'resolution': None,
                }
                order.append(key)
            seen[key]['occurrences'].append({'meal_idx': mi, 'item_idx': ii})
            if not seen[key].get('brand') and item.get('brand'):
                seen[key]['brand'] = item.get('brand')
    return [seen[k] for k in order]


def public_job_view(meta: dict, *, include_draft: bool = True) -> dict:
    out = {
        'id': meta['id'],
        'filename': meta.get('filename'),
        'ext': meta.get('ext'),
        'kind': prog.job_kind(meta),
        'image_count': int(meta.get('image_count') or 0),
        'files': [{'name': f.get('name')} for f in (meta.get('files') or [])],
        'sheets': meta.get('sheets') or [],
        'page_count': meta.get('page_count'),
        'status': meta.get('status'),
        'selected_sheet': meta.get('selected_sheet'),
        'selected_page': meta.get('selected_page'),
        'hint': meta.get('hint'),
        'warnings': meta.get('warnings') or [],
        'meal_plan_id': meta.get('meal_plan_id') or meta.get('program_id'),
        'match_items': meta.get('match_items') or [],
        'import_kind': 'meal',
    }
    if include_draft:
        out['draft'] = meta.get('draft')
    return out
