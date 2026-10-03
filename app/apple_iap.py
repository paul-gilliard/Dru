"""Apple In-App Purchase — catalogue + vérification transaction StoreKit 2 (JWS)."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import jwt

# Product IDs App Store Connect (auto-renewable)
ATHLETE_INDEPENDENT_PRODUCT = 'com.farmness.app.athlete.independent.monthly'
COACH_TIER_PRODUCTS = {
    1: 'com.farmness.app.coach.tier1.monthly',
    2: 'com.farmness.app.coach.tier2.monthly',
    3: 'com.farmness.app.coach.tier3.monthly',
}

PRODUCT_TO_PLAN: dict[str, tuple[str, int | None]] = {
    ATHLETE_INDEPENDENT_PRODUCT: ('athlete_independent', None),
    COACH_TIER_PRODUCTS[1]: ('coach_tier', 1),
    COACH_TIER_PRODUCTS[2]: ('coach_tier', 2),
    COACH_TIER_PRODUCTS[3]: ('coach_tier', 3),
}

ALL_PRODUCT_IDS = list(PRODUCT_TO_PLAN.keys())


def apple_product_id_for(kind: str, target_tier=None) -> str | None:
    if kind == 'athlete_independent':
        return ATHLETE_INDEPENDENT_PRODUCT
    if kind == 'coach_tier' and target_tier in COACH_TIER_PRODUCTS:
        return COACH_TIER_PRODUCTS[int(target_tier)]
    return None


def plan_for_product(product_id: str) -> tuple[str, int | None]:
    mapped = PRODUCT_TO_PLAN.get(product_id)
    if not mapped:
        raise ValueError(f'Produit Apple inconnu: {product_id}')
    return mapped


def _b64url_decode(segment: str) -> bytes:
    pad = '=' * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + pad)


def verify_storekit_jws(token: str) -> dict:
    """
    Vérifie une transaction StoreKit 2 (JWS) via le certificat x5c du header.
    Rejette les payloads sans productId / transactionId.
    """
    if not token or token.count('.') != 2:
        raise ValueError('JWS Apple invalide')

    try:
        header = jwt.get_unverified_header(token)
    except Exception as exc:
        raise ValueError('JWS Apple illisible') from exc

    x5c = header.get('x5c')
    if not x5c or not isinstance(x5c, list):
        raise ValueError('Certificat Apple (x5c) manquant dans la transaction')

    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
    except ImportError as exc:
        raise ValueError('cryptography requis pour vérifier les achats Apple') from exc

    try:
        leaf_der = base64.b64decode(x5c[0])
        cert = x509.load_der_x509_certificate(leaf_der, default_backend())
        public_key = cert.public_key()
        payload = jwt.decode(
            token,
            public_key,
            algorithms=['ES256'],
            options={'verify_aud': False},
        )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('Transaction Apple non vérifiable') from exc

    if not payload.get('productId') or not payload.get('transactionId'):
        raise ValueError('Transaction Apple incomplète')
    return payload


def transaction_still_active(payload: dict, *, now: datetime | None = None) -> bool:
    """True si expiresDate absent (non-sub) ou dans le futur."""
    now = now or datetime.now(timezone.utc)
    expires_ms = payload.get('expiresDate')
    if expires_ms is None:
        return True
    try:
        expires = datetime.fromtimestamp(int(expires_ms) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return False
    return expires > now


def decode_jws_payload_unverified(token: str) -> dict:
    """Debug / tests uniquement — ne pas utiliser pour granting entitlements."""
    parts = token.split('.')
    if len(parts) != 3:
        raise ValueError('JWS invalide')
    return json.loads(_b64url_decode(parts[1]))
