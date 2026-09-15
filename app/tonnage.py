"""Helpers tonnage — charge 0 kg (« à vide ») compte comme 1 kg."""


def effective_load_kg(load) -> float | None:
    """Charge utilisée pour le tonnage (reps × charge).

    - None → None (série sans charge renseignée)
    - 0 → 1.0 (barre à vide / poids de corps loggé à 0)
    - > 0 → valeur telle quelle
    """
    if load is None:
        return None
    try:
        v = float(load)
    except (TypeError, ValueError):
        return None
    if v < 0:
        return None
    return 1.0 if v == 0 else v


def series_tonnage(reps, load) -> float:
    """Tonnage d’une série ; 0 si reps/charge manquants."""
    if reps is None:
        return 0.0
    eff = effective_load_kg(load)
    if eff is None:
        return 0.0
    try:
        return float(reps) * eff
    except (TypeError, ValueError):
        return 0.0
