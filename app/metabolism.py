"""Métabolisme basal / TDEE — formules scientifiques + overrides athlète.

Sources principales :
- Mifflin MD et al., Am J Clin Nutr 1990 — Mifflin–St Jeor (BMR)
- Katch & McArdle — BMR via masse maigre si % masse grasse connu
- Multiplicateurs d’activité type FAO/WHO / pratique clinique courante (TDEE)

Indicatif uniquement : la dépense réelle varie (NEAT, entraînement, hormones…).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

ACTIVITY_FACTORS = {
    'sedentary': 1.2,      # peu ou pas d’exercice
    'light': 1.375,        # 1–3 séances / semaine
    'moderate': 1.55,      # 3–5 séances
    'active': 1.725,       # 6–7 séances
    'very_active': 1.9,    # entraînement intense + métier physique
}

ACTIVITY_LABELS = {
    'sedentary': 'Sédentaire',
    'light': 'Léger (1–3×/sem.)',
    'moderate': 'Modéré (3–5×/sem.)',
    'active': 'Actif (6–7×/sem.)',
    'very_active': 'Très actif',
}

TENDENCY_FACTORS = {
    # Ajustement heuristique (NEAT / ressenti) — pas une mesure labo
    'easy_store': 0.95,   # facilité à stocker → estime un peu moins de dépense
    'neutral': 1.0,
    'hard_gain': 1.05,    # difficulté à grossir → estime un peu plus de dépense
}

TENDENCY_LABELS = {
    'easy_store': 'Facilité à stocker / grossir',
    'neutral': 'Neutre / je ne sais pas',
    'hard_gain': 'Difficulté à grossir',
}

GOAL_LABELS = {
    'maintain': 'Maintien',
    'cut': 'Sèche (déficit)',
    'bulk': 'Prise de masse (surplus)',
}

DEFAULT_GOAL_DELTA = 250  # milieu de la fourchette 200–300
MIN_GOAL_DELTA = 150
MAX_GOAL_DELTA = 500

DISCLAIMER = (
    'Calcul indicatif (Mifflin–St Jeor ou Katch–McArdle). '
    'Ce n’est pas un avis médical. Si tu penses que ta dépense est différente, '
    'modifie le BMR ou le TDEE manuellement.'
)


def _age_years(birth_date: date | None, today: date | None = None) -> int | None:
    if not birth_date:
        return None
    today = today or date.today()
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years if years >= 14 else years  # allow teens but still compute


def mifflin_st_jeor(*, sex: str, weight_kg: float, height_cm: float, age_years: int) -> float:
    """BMR Mifflin–St Jeor (kcal/jour). sex: 'm' | 'f'."""
    base = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age_years
    if sex == 'm':
        return base + 5.0
    return base - 161.0


def katch_mcardle(*, weight_kg: float, body_fat_pct: float) -> float:
    """BMR Katch–McArdle via masse maigre (meilleur si % MG fiable)."""
    bf = max(3.0, min(60.0, float(body_fat_pct)))
    lbm = weight_kg * (1.0 - bf / 100.0)
    return 370.0 + 21.6 * lbm


def clamp_goal_delta(raw: int | None) -> int:
    try:
        v = int(raw if raw is not None else DEFAULT_GOAL_DELTA)
    except (TypeError, ValueError):
        v = DEFAULT_GOAL_DELTA
    return max(MIN_GOAL_DELTA, min(MAX_GOAL_DELTA, v))


def compute_metabolism(user, *, weight_kg: float | None = None) -> dict[str, Any]:
    """Calcule BMR/TDEE/cible à partir des champs User + poids (journal ou profil)."""
    sex = (getattr(user, 'sex', None) or '').strip().lower()
    if sex in ('male', 'man', 'homme'):
        sex = 'm'
    elif sex in ('female', 'woman', 'femme'):
        sex = 'f'
    if sex not in ('m', 'f'):
        sex = None

    height_cm = getattr(user, 'height_cm', None)
    birth = getattr(user, 'birth_date', None)
    age = _age_years(birth)
    bf = getattr(user, 'body_fat_pct', None)
    activity = getattr(user, 'activity_level', None) or 'moderate'
    if activity not in ACTIVITY_FACTORS:
        activity = 'moderate'
    tendency = getattr(user, 'metabolic_tendency', None) or 'neutral'
    if tendency not in TENDENCY_FACTORS:
        tendency = 'neutral'

    w = weight_kg
    if w is None:
        w = getattr(user, 'profile_weight_kg', None)

    formula = None
    formula_bmr = None
    missing = []

    if w is None or float(w) <= 0:
        missing.append('poids')
    if height_cm is None or float(height_cm) <= 0:
        missing.append('taille')
    if age is None or age < 10:
        missing.append('âge (date de naissance)')
    if not sex:
        missing.append('sexe')

    if bf is not None and w is not None and float(w) > 0:
        try:
            formula_bmr = katch_mcardle(weight_kg=float(w), body_fat_pct=float(bf))
            formula = 'katch_mcardle'
        except (TypeError, ValueError):
            formula_bmr = None

    if formula_bmr is None and not missing and w is not None and height_cm is not None and age is not None and sex:
        formula_bmr = mifflin_st_jeor(
            sex=sex, weight_kg=float(w), height_cm=float(height_cm), age_years=int(age),
        )
        formula = 'mifflin_st_jeor'

    bmr_override = getattr(user, 'bmr_override', None)
    tdee_override = getattr(user, 'tdee_override', None)

    bmr = int(round(float(bmr_override))) if bmr_override is not None else (
        int(round(formula_bmr)) if formula_bmr is not None else None
    )

    tdee = None
    if tdee_override is not None:
        tdee = int(round(float(tdee_override)))
    elif bmr is not None:
        raw = bmr * ACTIVITY_FACTORS[activity] * TENDENCY_FACTORS[tendency]
        tdee = int(round(raw))

    goal = getattr(user, 'energy_goal', None) or 'maintain'
    if goal not in GOAL_LABELS:
        goal = 'maintain'
    delta = clamp_goal_delta(getattr(user, 'energy_goal_delta', None))

    target = None
    if tdee is not None:
        if goal == 'cut':
            target = tdee - delta
        elif goal == 'bulk':
            target = tdee + delta
        else:
            target = tdee

    return {
        'sex': sex,
        'height_cm': float(height_cm) if height_cm is not None else None,
        'birth_date': birth.isoformat() if birth else None,
        'age_years': age,
        'weight_kg': float(w) if w is not None else None,
        'body_fat_pct': float(bf) if bf is not None else None,
        'activity_level': activity,
        'activity_label': ACTIVITY_LABELS[activity],
        'activity_factor': ACTIVITY_FACTORS[activity],
        'metabolic_tendency': tendency,
        'tendency_label': TENDENCY_LABELS[tendency],
        'tendency_factor': TENDENCY_FACTORS[tendency],
        'formula': formula,
        'formula_label': (
            'Katch–McArdle (masse maigre)' if formula == 'katch_mcardle'
            else 'Mifflin–St Jeor' if formula == 'mifflin_st_jeor'
            else None
        ),
        'formula_bmr': int(round(formula_bmr)) if formula_bmr is not None else None,
        'bmr_override': int(bmr_override) if bmr_override is not None else None,
        'tdee_override': int(tdee_override) if tdee_override is not None else None,
        'bmr': bmr,
        'tdee': tdee,
        'energy_goal': goal,
        'energy_goal_label': GOAL_LABELS[goal],
        'energy_goal_delta': delta,
        'target_kcal': target,
        'cut_suggestion': (tdee - DEFAULT_GOAL_DELTA) if tdee is not None else None,
        'bulk_suggestion': (tdee + DEFAULT_GOAL_DELTA) if tdee is not None else None,
        'missing_fields': missing,
        'balance_start_date': (
            user.energy_balance_start_date.isoformat()
            if getattr(user, 'energy_balance_start_date', None) else None
        ),
        'disclaimer': DISCLAIMER,
        'complete': bmr is not None and tdee is not None,
    }


def energy_balance_report(entries: list, *, target_kcal: int, start: date, end: date | None = None) -> dict[str, Any]:
    """Cumule déficit/surplus vs cible sur les jours avec kcal renseignées."""
    end = end or date.today()
    days = []
    for e in entries:
        d = e.entry_date if hasattr(e, 'entry_date') else None
        kcals = e.kcals if hasattr(e, 'kcals') else None
        if d is None or kcals is None:
            continue
        if d < start or d > end:
            continue
        bal = int(kcals) - int(target_kcal)
        days.append({
            'date': d.isoformat(),
            'kcals': int(kcals),
            'target_kcal': int(target_kcal),
            'balance': bal,
            'weight': getattr(e, 'weight', None),
        })
    days.sort(key=lambda x: x['date'])
    n = len(days)
    cumulative = sum(x['balance'] for x in days) if n else 0
    avg = round(cumulative / n) if n else None
    return {
        'start_date': start.isoformat(),
        'end_date': end.isoformat(),
        'days_with_data': n,
        'target_kcal': int(target_kcal),
        'cumulative_balance': cumulative,
        'avg_daily_balance': avg,
        'status': (
            'deficit' if cumulative < -50
            else 'surplus' if cumulative > 50
            else 'near_maintenance' if n else 'no_data'
        ),
        'days': days[-60:],  # cap payload
    }
