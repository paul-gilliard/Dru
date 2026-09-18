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
    'leg-curl': 'lying-leg-curl',
}

# Indices « machine / câble » dans un nom FR normalisé
_MACHINE_HINTS = (
    'machine', 'hammer', 'technogym', 'panatta', 'panata', 'nautilus',
    'guid', 'poulie', 'cable', 'smith', 'hack', 'presse', 'pulldown',
    'pec deck', 'butterfly', 'pupitre', 'leg press', 'presse a cuisses',
    'presse a jambes', 'iso lateral', 'isolateral',
)

# Slugs free-weight souvent collés à tort sur des machines guidées
_FREEWEIGHT_SLUGS = {
    'bench-press', 'incline-bench-press', 'overhead-press', 'squat', 'front-squat',
    'deadlift', 'bicep-curl', 'lateral-raise', 'front-raise', 'push-up',
    'barbell-row', 'pull-up', 'dip', 'forward-lunge', 'crunch', 'hip-thrust',
    'incline-dumbbell-press', 'dumbbell-bench-press',
}

# Nom normalisé (lower, sans accents) → slug. Les clés longues / spécifiques d’abord
# (le matcher choisit le plus long match).
EXERCISE_ANIMATION_MAP = {
    # --- Machines / câbles (priorité) ---
    # Hammer Strength / iso-latéral / guidé (même slug pack — pas d’asset marque dédié)
    'developpe couche hammer strength': 'machine-chest-press',
    'developpe couche hammerstrength': 'machine-chest-press',
    'developpe couche mts hammer': 'machine-chest-press',
    'chest press hammer': 'machine-chest-press',
    'chest press hammer strength': 'machine-chest-press',
    'presse pecs hammer': 'machine-chest-press',
    'presse pecs guidee': 'machine-chest-press',
    'developpe couche guide': 'machine-chest-press',
    'developpe couche guidee': 'machine-chest-press',
    'developpe couche machine': 'machine-chest-press',
    'developpe couche incline hammer': 'machine-chest-press',
    'developpe incline hammer strength': 'machine-chest-press',
    'developpe incline guidee': 'machine-chest-press',
    'developpe incline machine': 'machine-chest-press',
    'incline chest press hammer': 'machine-chest-press',
    'incline chest press machine': 'machine-chest-press',
    'decline chest press hammer': 'machine-chest-press',
    'developpe decline hammer': 'machine-chest-press',
    'developpe decline machine': 'machine-chest-press',
    'iso lateral chest press': 'machine-chest-press',
    'iso lateral chest press hammer': 'machine-chest-press',
    'developpe couche incline machine guidee': 'machine-chest-press',
    'developpe couche machine guidee': 'machine-chest-press',
    'developpe couche hammer': 'machine-chest-press',
    'developpe couche smith': 'smith-machine-bench-press',
    'smith developpe couche': 'smith-machine-bench-press',
    'developpe incline hammer': 'machine-chest-press',
    'developpe incline technogym': 'machine-chest-press',
    'developpe decline technogym': 'machine-chest-press',
    'developpe neutre technogym': 'machine-chest-press',
    'dev couche panatta guide': 'machine-chest-press',
    'dev couche panatta': 'machine-chest-press',
    'chest press machine': 'machine-chest-press',
    'machine chest press': 'machine-chest-press',
    'developpe machine': 'machine-chest-press',
    'presse pecs': 'machine-chest-press',
    'pec deck': 'pec-deck',
    'butterfly': 'pec-deck',
    'ecarte pecs': 'pec-deck',
    'ecarte pecs technogym': 'pec-deck',
    'pec deck hammer': 'pec-deck',
    'butterfly hammer': 'pec-deck',
    'reverse pec deck': 'reverse-pec-deck',
    'oiseau machine': 'reverse-pec-deck',
    'cable fly': 'cable-fly',
    'ecarte poulie': 'cable-fly',
    'incline cable fly': 'incline-cable-fly',
    'developpe militaire hammer': 'machine-shoulder-press',
    'developpe militaire hammer strength': 'machine-shoulder-press',
    'shoulder press hammer': 'machine-shoulder-press',
    'presse epaules hammer': 'machine-shoulder-press',
    'presse epaules guidee': 'machine-shoulder-press',
    'developpe epaules machine': 'machine-shoulder-press',
    'developpe militaire machine': 'machine-shoulder-press',
    'developpe militaire guidee': 'machine-shoulder-press',
    'iso lateral shoulder press': 'machine-shoulder-press',
    'developpe militaire technogym': 'machine-shoulder-press',
    'militaire nautilus guidee': 'machine-shoulder-press',
    'militaire nautilus': 'machine-shoulder-press',
    'machine epaules': 'machine-shoulder-press',
    'shoulder press machine': 'machine-shoulder-press',
    'machine shoulder press': 'machine-shoulder-press',
    'elevation laterale hammer': 'machine-lateral-raise',
    'elevation laterale machine': 'machine-lateral-raise',
    'machine lateral raise': 'machine-lateral-raise',
    'elevation laterale poulie complete hammer': 'cable-lateral-raise',
    'elevation laterale poulie': 'cable-lateral-raise',
    'elevation laterale poulies': 'cable-lateral-raise',
    'cable lateral raise': 'cable-lateral-raise',
    'elevation frontale poulie': 'cable-front-raise',
    'cable front raise': 'cable-front-raise',
    'cable rear delt fly': 'cable-rear-delt-fly',
    'face pull': 'face-pull',
    'lat pulldown': 'lat-pulldown',
    'tirage vertical': 'lat-pulldown',
    'tirage poitrine': 'lat-pulldown',
    'tirage vertical hammer': 'lat-pulldown',
    'pulldown hammer': 'lat-pulldown',
    'wide grip lat pulldown': 'wide-grip-lat-pulldown',
    'close grip lat pulldown': 'close-grip-lat-pulldown',
    'seated cable row': 'seated-row',
    'rowing poulie basse': 'seated-row',
    'tirage horizontal': 'seated-row',
    'rowing machine': 'machine-row',
    'machine row': 'machine-row',
    'rowing hammer': 'machine-row',
    'iso lateral row hammer': 'machine-row',
    'iso lateral low row hammer': 'machine-row',
    'low row hammer': 'machine-row',
    'chest supported row': 'chest-supported-row',
    't-bar row': 't-bar-row',
    't bar row': 't-bar-row',
    'single arm cable row': 'single-arm-cable-row',
    'assisted pull-up': 'assisted-pull-up',
    'assisted pull up': 'assisted-pull-up',
    'traction assistee': 'assisted-pull-up',
    'assisted chin-up': 'assisted-chin-up',
    'assisted dip': 'assisted-dip',
    'dips machine': 'assisted-dip',
    'dips triceps technogym': 'assisted-dip',
    'hack squat': 'hack-squat',
    'hack squat panatta': 'hack-squat',
    'hack squat panata': 'hack-squat',
    'hack squat hammer': 'hack-squat',
    'presse a cuisses': 'leg-press',
    'presse a jambes': 'leg-press',
    'leg press': 'leg-press',
    'presse a cuisses hammer': 'leg-press',
    'leg press hammer': 'leg-press',
    'press circulaire technogym': 'leg-press',
    'press vertical hammer': 'leg-press',
    'iso lateral leg press hammer': 'leg-press',
    'leg extension': 'leg-extension',
    'extension de jambes': 'leg-extension',
    'leg extension hammer': 'leg-extension',
    'extension jambes machine': 'leg-extension',
    'leg curl machine': 'seated-leg-curl',
    'leg curl assis': 'seated-leg-curl',
    'seated leg curl': 'seated-leg-curl',
    'leg curl hammer': 'seated-leg-curl',
    'leg curl allonge': 'lying-leg-curl',
    'lying leg curl': 'lying-leg-curl',
    'leg curl': 'lying-leg-curl',
    'pallof press': 'pallof-press',
    'half kneeling pallof press': 'half-kneeling-pallof-press',
    'rope hammer curl': 'rope-hammer-curl',
    'curl marteau corde': 'rope-hammer-curl',
    'straight arm pulldown': 'straight-arm-pulldown',
    'pulldown bras tendus': 'straight-arm-pulldown',
    'tricep pushdown': 'tricep-pushdown',
    'pushdown triceps': 'tricep-pushdown',
    'smith machine squat': 'smith-machine-squat',
    'squat smith': 'smith-machine-squat',
    'smith squat': 'smith-machine-squat',
    'fentes smith': 'smith-machine-reverse-lunge',
    "fentes smith's machine": 'smith-machine-bulgarian-split-squat',
    'smith machine bench press': 'smith-machine-bench-press',
    'smith machine hip thrust': 'smith-machine-hip-thrust',
    'smith machine romanian deadlift': 'smith-machine-romanian-deadlift',
    'smith machine bulgarian split squat': 'smith-machine-bulgarian-split-squat',
    'smith machine reverse lunge': 'smith-machine-reverse-lunge',
    'smith machine split squat': 'smith-machine-split-squat',
    'belt squat': 'belt-squat',
    'hip abduction machine': 'hip-abduction-machine',
    'abducteurs machine': 'hip-abduction-machine',
    'abducteurs': 'hip-abduction-machine',
    'hip adduction machine': 'hip-adduction-machine',
    'adducteurs machine': 'hip-adduction-machine',
    'adducteurs': 'hip-adduction-machine',
    'machine glute kickback': 'machine-glute-kickback',
    'cable kickback': 'cable-kickback',
    'cable pull through': 'cable-pull-through',
    'cable standing hip abduction': 'cable-standing-hip-abduction',
    'cable standing hip adduction': 'cable-standing-hip-adduction',
    'curl poulie': 'cable-curl',
    'cable curl': 'cable-curl',
    'curl biceps guide nautilus': 'preacher-curl',
    'curl machine': 'preacher-curl',
    'curl pupitre': 'preacher-curl',
    'curl pupitre technogym': 'preacher-curl',
    'preacher curl': 'preacher-curl',
    'extension triceps poulie haute': 'rope-tricep-pushdown',
    'extension triceps poulie': 'rope-tricep-pushdown',
    'triceps poulie': 'rope-tricep-pushdown',
    'rope tricep pushdown': 'rope-tricep-pushdown',
    'extension triceps poulie basse': 'overhead-tricep-extension',
    'cable crunch': 'cable-crunch',
    'crunch poulie': 'cable-crunch',
    'crunch machine nautilus': 'cable-crunch',
    'standing calf raise': 'standing-calf-raise',
    'mollets debout machine': 'standing-calf-raise',
    'seated calf raise': 'seated-calf-raise',
    'mollets assis machine': 'seated-calf-raise',
    'leg press calf raise': 'leg-press-calf-raise',
    'donkey calf raise': 'donkey-calf-raise',
    'reverse hyperextension': 'reverse-hyperextension',
    'extension dos poulie': 'cable-pull-through',
    'captains chair knee raise': 'captains-chair-knee-raise',
    'cable woodchop': 'cable-woodchop',
    'cable pallof hold': 'cable-pallof-hold',
    'hip trust hammer': 'hip-thrust',
    'hip thrust hammer': 'hip-thrust',

    # --- Free weight / bodyweight (génériques) ---
    'developpe couche': 'bench-press',
    'bench press': 'bench-press',
    'developpe incline': 'incline-bench-press',
    'developpe militaire': 'overhead-press',
    'overhead press': 'overhead-press',
    'arnold press': 'arnold-press',
    'developpe arnold': 'arnold-press',
    'squat': 'squat',
    'back squat': 'squat',
    'front squat': 'front-squat',
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
    'curl halteres': 'bicep-curl',
    'extension triceps': 'overhead-tricep-extension',
    'kickback': 'tricep-kickback',
    'elevation laterale': 'lateral-raise',
    'lateral raise': 'lateral-raise',
    'elevation frontale': 'front-raise',
    'oiseau': 'rear-delt-fly',
    'fentes': 'forward-lunge',
    'fente': 'forward-lunge',
    'lunge': 'forward-lunge',
    'mollets debout': 'standing-calf-raise',
    'mollets assis': 'seated-calf-raise',
    'crunch': 'crunch',
    'crunch machine': 'crunch',
    'planche': 'plank',
    'plank': 'plank',
    'ab wheel': 'ab-wheel',
    'hip thrust': 'hip-thrust',
    'good morning': 'good-morning',
    'shrug': 'shrug',
    'haussement epaules': 'shrug',
}


def normalize_exercise_name(name: str) -> str:
    import unicodedata
    import re
    text = (name or '').strip().lower()
    # Retire uniquement un suffixe perso type " (coach1)" / " (user@mail)" — pas "(hammer)".
    m = re.search(r'\s+\(([^)]+)\)\s*$', text)
    if m:
        inner = m.group(1).strip().lower()
        machineish = any(h in inner for h in (
            'hammer', 'machine', 'techno', 'panatta', 'panata', 'nautilus',
            'guide', 'smith', 'poulie', 'cable', 'presse',
        ))
        if not machineish and ('@' in inner or ' ' not in inner):
            text = text[: m.start()].rstrip()
    decomposed = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in decomposed if unicodedata.category(c) != 'Mn')
    for ch in ('(', ')', '[', ']', '/', '-', '_', "'", '’', '.', ','):
        text = text.replace(ch, ' ')
    return ' '.join(text.split())


def looks_like_machine_exercise(name: str) -> bool:
    # Sur le nom brut + normalisé (avant strip éventuel)
    raw = (name or '').lower()
    key = normalize_exercise_name(name)
    blob = f'{raw} {key}'
    return any(h in blob for h in _MACHINE_HINTS)


def slug_for_exercise_name(name: str) -> str | None:
    key = normalize_exercise_name(name)
    if not key:
        return None
    if key in EXERCISE_ANIMATION_MAP:
        return EXERCISE_ANIMATION_MAP[key]
    # Plus long match d’abord (évite « developpe couche » avant « … hammer »)
    best_slug = None
    best_len = 0
    for needle, slug in EXERCISE_ANIMATION_MAP.items():
        if len(needle) < 4:
            continue
        if needle in key or key in needle:
            if len(needle) > best_len:
                best_len = len(needle)
                best_slug = slug
    return best_slug


def should_replace_slug(name: str, current: str | None, suggested: str | None) -> bool:
    """True si on doit écrire `suggested` (vide, repair, ou machine mal mappée)."""
    if not suggested:
        return False
    cur = (current or '').strip() or None
    if not cur:
        return True
    if cur in SLUG_REPAIRS:
        return True
    if cur == suggested:
        return False
    if looks_like_machine_exercise(name) and cur in _FREEWEIGHT_SLUGS:
        return True
    # suggested plus « machine » que current
    machine_tokens = ('machine', 'cable', 'smith', 'hack', 'pec-deck', 'pulldown', 'assisted')
    sug_m = any(t in suggested for t in machine_tokens)
    cur_m = any(t in cur for t in machine_tokens)
    if looks_like_machine_exercise(name) and sug_m and not cur_m:
        return True
    return False


def backfill_animation_slugs(db_session, Exercise):
    """Remplit / répare animation_slug sur les communs. Retourne le nombre mis à jour."""
    updated = 0
    rows = Exercise.query.filter_by(owner_id=None).all()
    for ex in rows:
        current = (ex.animation_slug or '').strip() or None
        if current and current in SLUG_REPAIRS:
            suggested = SLUG_REPAIRS[current]
        else:
            suggested = slug_for_exercise_name(ex.name)
        if not should_replace_slug(ex.name, current, suggested):
            continue
        ex.animation_slug = suggested
        if ex.media_status in (None, 'none'):
            ex.media_status = 'approved'
        updated += 1
    if updated:
        db_session.commit()
    return updated
