"""
Seed / backfill `animation_slug` pour les exercices communs.
Mapping FR (et variantes) → slugs @bryllim/workout-guide (CC BY-SA 4.0).
Slugs = ids réels du package npm (manifest.json), pas des noms inventés.
"""
from __future__ import annotations

# Anciens slugs incorrects → slug CDN valide (réparation one-shot)
SLUG_REPAIRS = {
    'barbell-bench-press': 'bench-press',
    'incline-barbell-bench-press': 'incline-bench-press',
    'back-squat': 'squat',
    'barbell-curl': 'bicep-curl',
    'dumbbell-curl': 'bicep-curl',
    'triceps-extension': 'overhead-tricep-extension',
    'triceps-kickback': 'tricep-kickback',
    'lunge': 'forward-lunge',
}

# Nom normalisé (lower, sans accents gérés à l'appel) → slug
EXERCISE_ANIMATION_MAP = {
    'développé couché': 'bench-press',
    'developpe couche': 'bench-press',
    'bench press': 'bench-press',
    'développé incliné': 'incline-bench-press',
    'developpe incline': 'incline-bench-press',
    'développé militaire': 'overhead-press',
    'developpe militaire': 'overhead-press',
    'overhead press': 'overhead-press',
    'arnold press': 'arnold-press',
    'développé arnold': 'arnold-press',
    'squat': 'squat',
    'back squat': 'squat',
    'front squat': 'front-squat',
    'soulevé de terre': 'deadlift',
    'souleve de terre': 'deadlift',
    'deadlift': 'deadlift',
    'rowing barre': 'barbell-row',
    'row barre': 'barbell-row',
    'traction': 'pull-up',
    'tractions': 'pull-up',
    'pull-up': 'pull-up',
    'pull up': 'pull-up',
    'chin-up': 'chin-up',
    'dips': 'dip',
    'dip': 'dip',
    'pompes': 'push-up',
    'pompe': 'push-up',
    'push-up': 'push-up',
    'push up': 'push-up',
    'curl biceps': 'bicep-curl',
    'curl barre': 'bicep-curl',
    'curl haltères': 'bicep-curl',
    'curl halteres': 'bicep-curl',
    'extension triceps': 'overhead-tricep-extension',
    'kickback': 'tricep-kickback',
    'élévation latérale': 'lateral-raise',
    'elevation laterale': 'lateral-raise',
    'lateral raise': 'lateral-raise',
    'élévation frontale': 'front-raise',
    'elevation frontale': 'front-raise',
    'oiseau': 'rear-delt-fly',
    'face pull': 'face-pull',
    'leg press': 'leg-press',
    'presse à cuisses': 'leg-press',
    'presse a cuisses': 'leg-press',
    'leg extension': 'leg-extension',
    'leg curl': 'lying-leg-curl',
    'fentes': 'forward-lunge',
    'fente': 'forward-lunge',
    'lunge': 'forward-lunge',
    'mollets debout': 'standing-calf-raise',
    'mollets assis': 'seated-calf-raise',
    'crunch': 'crunch',
    'planche': 'plank',
    'plank': 'plank',
    'ab wheel': 'ab-wheel',
    'hip thrust': 'hip-thrust',
    'good morning': 'good-morning',
    'shrug': 'shrug',
    'haussement épaules': 'shrug',
    'haussement epaules': 'shrug',
}


def normalize_exercise_name(name: str) -> str:
    import unicodedata
    text = (name or '').strip().lower()
    # retire suffixe perso " (username)"
    if ' (' in text and text.endswith(')'):
        text = text.rsplit(' (', 1)[0]
    decomposed = unicodedata.normalize('NFD', text)
    return ''.join(c for c in decomposed if unicodedata.category(c) != 'Mn')


def slug_for_exercise_name(name: str) -> str | None:
    key = normalize_exercise_name(name)
    if key in EXERCISE_ANIMATION_MAP:
        return EXERCISE_ANIMATION_MAP[key]
    # match partiel : si une clé est contenue dans le nom
    for needle, slug in EXERCISE_ANIMATION_MAP.items():
        if needle in key or key in needle:
            return slug
    return None


def backfill_animation_slugs(db_session, Exercise):
    """Remplit / répare animation_slug sur les communs. Retourne le nombre mis à jour."""
    updated = 0
    rows = Exercise.query.filter_by(owner_id=None).all()
    for ex in rows:
        current = (ex.animation_slug or '').strip() or None
        if current and current in SLUG_REPAIRS:
            ex.animation_slug = SLUG_REPAIRS[current]
            if ex.media_status in (None, 'none'):
                ex.media_status = 'approved'
            updated += 1
            continue
        if current:
            continue
        slug = slug_for_exercise_name(ex.name)
        if not slug:
            continue
        ex.animation_slug = slug
        if ex.media_status in (None, 'none'):
            ex.media_status = 'approved'
        updated += 1
    if updated:
        db_session.commit()
    return updated
