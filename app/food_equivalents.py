"""Matching d'aliments équivalents (kcal calées + macros ±20 %)."""
from __future__ import annotations

from typing import Any, Iterable


REL_TOL = 0.20
# Plancher absolu par macro (g) — lipids trop larges → vinaigre ≈ riz
ABS_MIN = {
    'proteins': 3.0,
    'carbs': 5.0,
    'lipids': 1.0,
    'kcals': 15.0,
}
MIN_G = 10.0
MAX_G = 500.0
TOP_N = 20


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def portion_macros(food, quantity: float) -> dict[str, float]:
    factor = (quantity or 100) / 100.0
    return {
        'kcals': _f(getattr(food, 'kcal', 0)) * factor,
        'proteins': _f(getattr(food, 'proteins', 0)) * factor,
        'lipids': _f(getattr(food, 'lipids', 0)) * factor,
        'carbs': _f(getattr(food, 'carbs', 0)) * factor,
    }


def suggest_quantity(target_kcals: float, kcal_per_100g: float) -> float | None:
    kcal_per_100g = _f(kcal_per_100g)
    if kcal_per_100g <= 0 or target_kcals <= 0:
        return None
    grams = round(target_kcals / kcal_per_100g * 100.0)
    return float(max(MIN_G, min(MAX_G, grams)))


def _within_tol(target: float, actual: float, *, abs_min: float) -> bool:
    target = abs(target)
    actual = abs(actual)
    tol = max(abs_min, target * REL_TOL)
    return abs(actual - target) <= tol


def _rel_error(target: float, actual: float, *, abs_min: float) -> float:
    target = abs(target)
    if target < abs_min:
        return abs(actual - target) / abs_min
    return abs(actual - target) / target


def candidate_dict(food, quantity: float, target: dict[str, float], score: float) -> dict[str, Any]:
    macros = portion_macros(food, quantity)
    return {
        'food_id': food.id,
        'food_name': food.name,
        'brand': getattr(food, 'brand', None),
        'is_personal': bool(getattr(food, 'owner_id', None)),
        'quantity': quantity,
        'kcals': round(macros['kcals'], 1),
        'proteins': round(macros['proteins'], 1),
        'lipids': round(macros['lipids'], 1),
        'carbs': round(macros['carbs'], 1),
        'delta_kcals': round(macros['kcals'] - target['kcals'], 1),
        'delta_proteins': round(macros['proteins'] - target['proteins'], 1),
        'delta_lipids': round(macros['lipids'] - target['lipids'], 1),
        'delta_carbs': round(macros['carbs'] - target['carbs'], 1),
        'score': round(score, 4),
    }


def find_food_equivalents(
    source_food,
    quantity: float,
    candidates: Iterable,
    *,
    limit: int = TOP_N,
) -> list[dict[str, Any]]:
    """Retourne des candidats scorés (meilleur score = plus proche)."""
    qty = float(quantity or 100)
    target = portion_macros(source_food, qty)
    source_id = getattr(source_food, 'id', None)
    results: list[dict[str, Any]] = []

    for food in candidates:
        if food is None or getattr(food, 'id', None) == source_id:
            continue
        # Même aliment sous un autre id (ex. marque) : déjà géré côté nom côté UI si besoin
        kcal100 = _f(getattr(food, 'kcal', 0))
        g = suggest_quantity(target['kcals'], kcal100)
        if g is None:
            continue
        macros = portion_macros(food, g)
        if not (
            _within_tol(target['kcals'], macros['kcals'], abs_min=ABS_MIN['kcals'])
            and _within_tol(target['proteins'], macros['proteins'], abs_min=ABS_MIN['proteins'])
            and _within_tol(target['carbs'], macros['carbs'], abs_min=ABS_MIN['carbs'])
            and _within_tol(target['lipids'], macros['lipids'], abs_min=ABS_MIN['lipids'])
        ):
            continue
        # Profil macro dominant : un féculent ne match pas un assaisonnement
        t_sum = target['proteins'] + target['carbs'] + target['lipids']
        m_sum = macros['proteins'] + macros['carbs'] + macros['lipids']
        if t_sum >= 10 and m_sum >= 10:
            t_carb_share = target['carbs'] / t_sum
            m_carb_share = macros['carbs'] / m_sum
            if abs(t_carb_share - m_carb_share) > 0.25:
                continue
        score = (
            _rel_error(target['proteins'], macros['proteins'], abs_min=ABS_MIN['proteins'])
            + _rel_error(target['carbs'], macros['carbs'], abs_min=ABS_MIN['carbs'])
            + _rel_error(target['lipids'], macros['lipids'], abs_min=ABS_MIN['lipids'])
            + 0.35 * _rel_error(target['kcals'], macros['kcals'], abs_min=ABS_MIN['kcals'])
        ) / 3.35
        results.append(candidate_dict(food, g, target, score))

    results.sort(key=lambda r: (r['score'], abs(r['delta_kcals']), r['food_name'].lower()))
    return results[: max(1, int(limit or TOP_N))]
