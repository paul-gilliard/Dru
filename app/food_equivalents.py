"""Matching d'aliments équivalents (kcal calées + macros ±20 %)."""
from __future__ import annotations

from typing import Any, Iterable


REL_TOL = 0.20
ABS_MIN_G = 2.0
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


def _within_tol(target: float, actual: float) -> bool:
    target = abs(target)
    actual = abs(actual)
    tol = max(ABS_MIN_G, target * REL_TOL)
    return abs(actual - target) <= tol


def _rel_error(target: float, actual: float) -> float:
    target = abs(target)
    if target < ABS_MIN_G:
        return abs(actual - target) / ABS_MIN_G
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
        kcal100 = _f(getattr(food, 'kcal', 0))
        g = suggest_quantity(target['kcals'], kcal100)
        if g is None:
            continue
        macros = portion_macros(food, g)
        if not (
            _within_tol(target['proteins'], macros['proteins'])
            and _within_tol(target['carbs'], macros['carbs'])
            and _within_tol(target['lipids'], macros['lipids'])
        ):
            continue
        score = (
            _rel_error(target['proteins'], macros['proteins'])
            + _rel_error(target['carbs'], macros['carbs'])
            + _rel_error(target['lipids'], macros['lipids'])
            + 0.25 * _rel_error(target['kcals'], macros['kcals'])
        ) / 3.25
        results.append(candidate_dict(food, g, target, score))

    results.sort(key=lambda r: (r['score'], abs(r['delta_kcals']), r['food_name'].lower()))
    return results[: max(1, int(limit or TOP_N))]
