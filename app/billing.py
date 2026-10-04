"""Abonnements Stripe Checkout (live/test via clés env) + suivi paiements admin."""
from __future__ import annotations

import html as html_lib
import json
import re
from datetime import datetime

import stripe
from flask import Blueprint, current_app, jsonify, request

from app import db
from app.mobile_auth import admin_required, login_required
from app.apple_iap import (
    ALL_PRODUCT_IDS,
    apple_product_id_for,
    plan_for_product,
    transaction_still_active,
    verify_storekit_jws,
)
from app.models import SubscriptionPayment, User

billing_bp = Blueprint('billing', __name__)

# Montants serveur (centimes) — mensuel
ATHLETE_INDEPENDENT_CENTS = 199  # 1,99 €
COACH_TIER_CENTS = {
    1: 999,   # 9,99 €
    2: 2499,  # 24,99 €
    3: 4999,  # 49,99 €
}
COACH_TIER_LABELS = {
    0: 'Sans abonnement',
    1: 'Niveau 1 — 3 athlètes',
    2: 'Niveau 2 — 10 athlètes',
    3: 'Niveau 3 — illimité',
}


def _stripe_ready():
    key = (current_app.config.get('STRIPE_SECRET_KEY') or '').strip()
    if not key:
        return False
    stripe.api_key = key
    return True


def _public_base():
    return (current_app.config.get('PUBLIC_BASE_URL') or '').rstrip('/')


def _checkout_url_allowed(url: str) -> bool:
    """Refuse les success/cancel_url arbitraires (open redirect / phishing)."""
    import os
    from urllib.parse import urlparse

    u = (url or '').strip()
    if not u:
        return True
    # Deep links app
    if u.startswith('farmness://') or u.startswith('exp://'):
        return True
    base = _public_base()
    if base and u.startswith(base):
        return True
    allow = [
        x.strip() for x in (os.environ.get('BILLING_URL_ALLOWLIST') or '').split(',') if x.strip()
    ]
    for prefix in allow:
        if u.startswith(prefix):
            return True
    parsed = urlparse(u)
    if parsed.scheme not in ('https', 'http'):
        return False
    host = (parsed.hostname or '').lower()
    # Dev local uniquement si app en développement
    if current_app.config.get('IS_DEVELOPMENT') and host in ('localhost', '127.0.0.1'):
        return True
    return False


def _amount_euros(kind: str, target_tier) -> float:
    if kind == 'athlete_independent':
        return ATHLETE_INDEPENDENT_CENTS / 100.0
    if kind == 'coach_tier' and target_tier in COACH_TIER_CENTS:
        return COACH_TIER_CENTS[int(target_tier)] / 100.0
    return 0.0


def _plan_label(kind: str, target_tier) -> str:
    if kind == 'athlete_independent':
        return 'Module Indépendant'
    if kind == 'athlete_free':
        return 'Athlète Free'
    if kind == 'coach_tier':
        return COACH_TIER_LABELS.get(int(target_tier or 0), f'Niveau {target_tier}')
    return kind


def apply_subscription_change(user: User, kind: str, target_tier=None):
    """Applique le plan sur le user (après paiement Stripe ou action admin)."""
    if kind == 'athlete_independent':
        if user.role != 'athlete':
            raise ValueError('Réservé aux athlètes')
        user.independent_module = True
    elif kind == 'athlete_free':
        if user.role != 'athlete':
            raise ValueError('Réservé aux athlètes')
        user.independent_module = False
    elif kind == 'coach_tier':
        if user.role != 'coach':
            raise ValueError('Réservé aux coachs')
        tier = int(target_tier)
        if tier not in (0, 1, 2, 3):
            raise ValueError('tier invalide')
        user.subscription_tier = tier
    else:
        raise ValueError('kind invalide')


def record_admin_manual_change(user: User, kind: str, target_tier, admin: User, note: str | None = None):
    """Log un upgrade/downgrade fait par le superadmin sans Stripe."""
    pay = SubscriptionPayment(
        user_id=user.id,
        kind=kind,
        target_tier=target_tier if kind == 'coach_tier' else None,
        amount_euros=0.0,
        billing_period='monthly',
        source='admin_manual',
        status='paid',
        note=note or 'Upgrade manuel (superadmin)',
        resolved_at=datetime.utcnow(),
        resolved_by_id=admin.id if admin else None,
    )
    db.session.add(pay)
    return pay


def _fulfill_payment(pay: SubscriptionPayment, *, payment_intent=None):
    if pay.status == 'paid':
        return pay
    user = User.query.get(pay.user_id)
    if not user:
        raise ValueError('Utilisateur introuvable')
    apply_subscription_change(user, pay.kind, pay.target_tier)
    pay.status = 'paid'
    pay.resolved_at = datetime.utcnow()
    if payment_intent:
        pay.stripe_payment_intent = payment_intent
    # Coach hors quota après downgrade : trim si besoin
    if user.role == 'coach' and pay.kind == 'coach_tier':
        try:
            from app.mobile_api import _enforce_coach_quota_or_trim
            _enforce_coach_quota_or_trim(user)
        except Exception:
            pass
    return pay


def _current_plan_payload(user: User):
    if user.role == 'athlete':
        independent = bool(user.independent_module)
        return {
            'role': 'athlete',
            'independent_module': independent,
            'label': 'Indépendant' if independent else 'Free',
            'price_euros': 1.99 if independent else 0,
            'plans': [
                {
                    'kind': 'athlete_free',
                    'label': 'Free',
                    'price_euros': 0,
                    'price_label': 'Gratuit',
                    'blurb': 'Programmes, nutrition, banques perso',
                    'current': not independent,
                    'apple_product_id': None,
                },
                {
                    'kind': 'athlete_independent',
                    'label': 'Indépendant',
                    'price_euros': 1.99,
                    'price_label': '1,99 € / mois',
                    'blurb': 'Stats + Easy Bilan',
                    'current': independent,
                    'apple_product_id': apple_product_id_for('athlete_independent'),
                },
            ],
        }
    # coach
    tier = int(user.subscription_tier or 0)
    plans = [
        {
            'kind': 'coach_tier',
            'target_tier': 0,
            'label': COACH_TIER_LABELS[0],
            'price_euros': 0,
            'price_label': 'Gratuit',
            'blurb': '0 athlète — abonnement requis pour coacher',
            'current': tier == 0,
            'apple_product_id': None,
        },
        {
            'kind': 'coach_tier',
            'target_tier': 1,
            'label': COACH_TIER_LABELS[1],
            'price_euros': 9.99,
            'price_label': '9,99 € / mois',
            'blurb': 'Jusqu’à 3 athlètes',
            'current': tier == 1,
            'apple_product_id': apple_product_id_for('coach_tier', 1),
        },
        {
            'kind': 'coach_tier',
            'target_tier': 2,
            'label': COACH_TIER_LABELS[2],
            'price_euros': 24.99,
            'price_label': '24,99 € / mois',
            'blurb': 'Jusqu’à 10 athlètes',
            'current': tier == 2,
            'apple_product_id': apple_product_id_for('coach_tier', 2),
        },
        {
            'kind': 'coach_tier',
            'target_tier': 3,
            'label': COACH_TIER_LABELS[3],
            'price_euros': 49.99,
            'price_label': '49,99 € / mois',
            'blurb': 'Athlètes illimités',
            'current': tier == 3,
            'apple_product_id': apple_product_id_for('coach_tier', 3),
        },
    ]
    return {
        'role': 'coach',
        'subscription_tier': tier,
        'athlete_limit': user.athlete_limit(),
        'label': COACH_TIER_LABELS.get(tier, f'Niveau {tier}'),
        'price_euros': _amount_euros('coach_tier', tier) if tier else 0,
        'plans': plans,
    }


def _clear_limbo_pendings(user_id: int) -> bool:
    """
    Annule les demandes qui laissent le coach/athlète dans un entre-deux
    (demande admin / checkout Stripe abandonné). L'abonnement reste binaire :
    appliqué après paiement, sinon inchangé.
    """
    now = datetime.utcnow()
    changed = False
    n_manual = SubscriptionPayment.query.filter_by(
        user_id=user_id, status='pending', source='manual_request',
    ).update({'status': 'cancelled', 'resolved_at': now}, synchronize_session=False)
    if n_manual:
        changed = True
    from datetime import timedelta
    cutoff = now - timedelta(minutes=30)
    n_stripe = (
        SubscriptionPayment.query.filter(
            SubscriptionPayment.user_id == user_id,
            SubscriptionPayment.status == 'pending',
            SubscriptionPayment.source == 'stripe',
            SubscriptionPayment.created_at < cutoff,
        ).update({'status': 'cancelled', 'resolved_at': now}, synchronize_session=False)
    )
    if n_stripe:
        changed = True
    return changed


@billing_bp.get('/me/subscription')
@login_required
def get_my_subscription():
    user = request.current_user
    if user.role not in ('athlete', 'coach'):
        return jsonify({'error': 'Réservé athlète / coach'}), 403
    if _clear_limbo_pendings(user.id):
        db.session.commit()
    history = (
        SubscriptionPayment.query.filter_by(user_id=user.id)
        .order_by(SubscriptionPayment.created_at.desc())
        .limit(20)
        .all()
    )
    payload = {
        'current': _current_plan_payload(user),
        'pending': None,
        'history': [p.to_dict() for p in history],
        'stripe_configured': bool((current_app.config.get('STRIPE_SECRET_KEY') or '').strip()),
        'apple_iap_products': ALL_PRODUCT_IDS,
    }
    # Hint carte test uniquement en développement local — jamais en prod.
    if current_app.config.get('IS_DEVELOPMENT'):
        payload['test_card_hint'] = (
            'Carte test Stripe : 4242 4242 4242 4242 — date future — CVC quelconque'
        )
    return jsonify(payload)


@billing_bp.post('/me/subscription/checkout')
@login_required
def create_checkout():
    """Crée une session Stripe Checkout (abonnement mensuel). Paiement OK → upgrade auto."""
    user = request.current_user
    if user.role not in ('athlete', 'coach'):
        return jsonify({'error': 'Réservé athlète / coach'}), 403

    data = request.get_json(silent=True) or {}
    platform = (data.get('platform') or request.headers.get('X-Client-Platform') or '').strip().lower()
    if platform == 'ios':
        return jsonify({
            'error': 'Sur iOS, les abonnements passent par les achats intégrés Apple (In-App Purchase).',
            'code': 'USE_APPLE_IAP',
        }), 400

    if not _stripe_ready():
        return jsonify({
            'error': 'Paiement indisponible pour le moment. Contacte le support Farmness.',
            'code': 'STRIPE_NOT_CONFIGURED',
        }), 503

    kind = (data.get('kind') or '').strip()
    target_tier = data.get('target_tier')
    success_url = (data.get('success_url') or '').strip()
    cancel_url = (data.get('cancel_url') or '').strip()
    if success_url and not _checkout_url_allowed(success_url):
        return jsonify({'error': 'success_url non autorisée'}), 400
    if cancel_url and not _checkout_url_allowed(cancel_url):
        return jsonify({'error': 'cancel_url non autorisée'}), 400

    if kind == 'athlete_independent':
        if user.role != 'athlete':
            return jsonify({'error': 'Réservé athlète'}), 403
        if user.independent_module:
            return jsonify({'error': 'Tu es déjà en Indépendant'}), 400
        target_tier = None
        cents = ATHLETE_INDEPENDENT_CENTS
        product_name = 'Farmness — Module Indépendant (mensuel)'
    elif kind == 'coach_tier':
        if user.role != 'coach':
            return jsonify({'error': 'Réservé coach'}), 403
        try:
            target_tier = int(target_tier)
        except (TypeError, ValueError):
            return jsonify({'error': 'target_tier requis'}), 400
        if target_tier not in (1, 2, 3):
            return jsonify({'error': 'Choisis un niveau payant (1–3). Pour annuler, utilise le downgrade.'}), 400
        if int(user.subscription_tier or 0) == target_tier:
            return jsonify({'error': 'Tu es déjà sur ce niveau'}), 400
        cents = COACH_TIER_CENTS[target_tier]
        product_name = f'Farmness — {COACH_TIER_LABELS[target_tier]} (mensuel)'
    else:
        return jsonify({'error': 'kind invalide (athlete_independent | coach_tier)'}), 400

    # Annule tout pending précédent (manual + stripe) avant un nouveau checkout
    SubscriptionPayment.query.filter_by(
        user_id=user.id, status='pending',
    ).update({'status': 'cancelled', 'resolved_at': datetime.utcnow()}, synchronize_session=False)

    base = _public_base()
    if not success_url:
        success_url = (
            f'{base}/api/billing/return?status=success&session_id={{CHECKOUT_SESSION_ID}}'
            if base else 'https://example.com/success?session_id={CHECKOUT_SESSION_ID}'
        )
    if not cancel_url:
        cancel_url = (
            f'{base}/api/billing/return?status=cancel'
            if base else 'https://example.com/cancel'
        )

    pay = SubscriptionPayment(
        user_id=user.id,
        kind=kind,
        target_tier=target_tier,
        amount_euros=cents / 100.0,
        billing_period='monthly',
        source='stripe',
        status='pending',
        note=_plan_label(kind, target_tier),
    )
    db.session.add(pay)
    db.session.flush()

    try:
        # mode=subscription + price_data.recurring : pas besoin de Price IDs
        # pré-créés (fonctionne en Live sans catalogue Stripe séparé).
        session = stripe.checkout.Session.create(
            mode='subscription',
            payment_method_types=['card'],
            line_items=[{
                'quantity': 1,
                'price_data': {
                    'currency': 'eur',
                    'unit_amount': cents,
                    'recurring': {'interval': 'month'},
                    'product_data': {
                        'name': product_name,
                        'description': 'Abonnement mensuel Farmness',
                    },
                },
            }],
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=(user.email or None),
            client_reference_id=str(user.id),
            metadata={
                'payment_id': str(pay.id),
                'user_id': str(user.id),
                'kind': kind,
                'target_tier': '' if target_tier is None else str(target_tier),
            },
            subscription_data={
                'metadata': {
                    'payment_id': str(pay.id),
                    'user_id': str(user.id),
                    'kind': kind,
                    'target_tier': '' if target_tier is None else str(target_tier),
                },
            },
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('stripe checkout failed')
        return jsonify({'error': 'Paiement impossible. Réessaie ou contacte le support.'}), 502

    pay.stripe_session_id = session.id
    db.session.commit()
    return jsonify({
        'checkout_url': session.url,
        'session_id': session.id,
        'payment_id': pay.id,
        'amount_euros': pay.amount_euros,
    })


@billing_bp.post('/me/subscription/confirm')
@login_required
def confirm_checkout():
    """Après retour app : vérifie la session Stripe et upgrade si payée."""
    user = request.current_user
    if not _stripe_ready():
        return jsonify({'error': 'Paiement indisponible pour le moment.', 'code': 'STRIPE_NOT_CONFIGURED'}), 503
    data = request.get_json(silent=True) or {}
    session_id = (data.get('session_id') or '').strip()
    if not session_id:
        return jsonify({'error': 'session_id requis'}), 400

    pay = SubscriptionPayment.query.filter_by(stripe_session_id=session_id).first()
    if not pay or pay.user_id != user.id:
        return jsonify({'error': 'Paiement introuvable'}), 404
    if pay.status == 'paid':
        return jsonify({'ok': True, 'payment': pay.to_dict(), 'user': user.to_dict()})

    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception as e:
        current_app.logger.exception('stripe session retrieve failed')
        return jsonify({'error': 'Paiement impossible à vérifier. Réessaie dans un instant.'}), 502

    if session.payment_status != 'paid' and session.status != 'complete':
        return jsonify({'error': 'Paiement pas encore confirmé', 'payment_status': session.payment_status}), 402

    try:
        _fulfill_payment(pay, payment_intent=getattr(session, 'payment_intent', None))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

    db.session.refresh(user)
    return jsonify({'ok': True, 'payment': pay.to_dict(), 'user': user.to_dict()})


@billing_bp.post('/me/subscription/apple/confirm')
@login_required
def confirm_apple_purchase():
    """Valide une transaction StoreKit 2 (JWS) et applique l'abonnement."""
    user = request.current_user
    if user.role not in ('athlete', 'coach'):
        return jsonify({'error': 'Réservé athlète / coach'}), 403

    data = request.get_json(silent=True) or {}
    signed = (data.get('signed_transaction') or data.get('transactionReceipt') or '').strip()
    if not signed:
        return jsonify({'error': 'signed_transaction requis'}), 400

    try:
        payload = verify_storekit_jws(signed)
    except ValueError as e:
        return jsonify({'error': 'Achat Apple invalide. Relance l\'achat ou utilise « Restaurer les achats ».', 'code': 'APPLE_JWS_INVALID'}), 400

    product_id = str(payload.get('productId') or '')
    transaction_id = str(payload.get('transactionId') or '')
    original_transaction_id = str(payload.get('originalTransactionId') or transaction_id)
    bundle_id = str(payload.get('bundleId') or '')
    if bundle_id and bundle_id != 'com.farmness.app':
        return jsonify({'error': 'Achat Apple non reconnu pour cette app'}), 400
    if not transaction_still_active(payload):
        return jsonify({'error': 'Abonnement Apple expiré', 'code': 'APPLE_EXPIRED'}), 400

    try:
        kind, target_tier = plan_for_product(product_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    if kind.startswith('athlete') and user.role != 'athlete':
        return jsonify({'error': 'Produit réservé athlète'}), 403
    if kind == 'coach_tier' and user.role != 'coach':
        return jsonify({'error': 'Produit réservé coach'}), 403

    existing = SubscriptionPayment.query.filter_by(apple_transaction_id=transaction_id).first()
    if existing:
        if existing.user_id != user.id:
            return jsonify({'error': 'Transaction déjà liée à un autre compte'}), 409
        db.session.refresh(user)
        return jsonify({'ok': True, 'payment': existing.to_dict(), 'user': user.to_dict()})

    pay = SubscriptionPayment(
        user_id=user.id,
        kind=kind,
        target_tier=target_tier if kind == 'coach_tier' else None,
        amount_euros=_amount_euros(kind, target_tier),
        billing_period='monthly',
        source='apple',
        status='pending',
        apple_product_id=product_id,
        apple_transaction_id=transaction_id,
        apple_original_transaction_id=original_transaction_id,
        note='In-App Purchase StoreKit',
    )
    db.session.add(pay)
    try:
        _fulfill_payment(pay)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

    db.session.refresh(user)
    return jsonify({'ok': True, 'payment': pay.to_dict(), 'user': user.to_dict()})


@billing_bp.post('/me/subscription')
@login_required
def request_subscription():
    """Plus de file « demande admin » : upgrade = Stripe, sinon Superadmin via Users.
    Downgrade free/tier0 → appliqué tout de suite.
    """
    user = request.current_user
    if user.role not in ('athlete', 'coach'):
        return jsonify({'error': 'Réservé athlète / coach'}), 403
    data = request.get_json(silent=True) or {}
    kind = (data.get('kind') or '').strip()
    target_tier = data.get('target_tier')

    if kind == 'athlete_free' or (kind == 'coach_tier' and int(target_tier or 0) == 0):
        return downgrade_subscription()

    if kind == 'athlete_independent':
        if user.role != 'athlete':
            return jsonify({'error': 'Réservé athlète'}), 403
        if user.independent_module:
            return jsonify({'error': 'Tu es déjà en Indépendant'}), 400
    elif kind == 'coach_tier':
        if user.role != 'coach':
            return jsonify({'error': 'Réservé coach'}), 403
        try:
            target_tier = int(target_tier)
        except (TypeError, ValueError):
            return jsonify({'error': 'target_tier requis'}), 400
        if target_tier not in (1, 2, 3):
            return jsonify({'error': 'Niveau payant 1–3 requis'}), 400
        if int(user.subscription_tier or 0) == target_tier:
            return jsonify({'error': 'Tu es déjà sur ce niveau'}), 400
    else:
        return jsonify({'error': 'kind invalide'}), 400

    if _clear_limbo_pendings(user.id):
        db.session.commit()

    if _stripe_ready():
        return jsonify({
            'error': 'Utilise le paiement Stripe pour upgrader.',
            'code': 'USE_STRIPE_CHECKOUT',
            'stripe_configured': True,
        }), 409

    return jsonify({
        'error': 'Paiement en ligne indisponible. Demande à Superadmin d’activer ton abonnement.',
        'code': 'STRIPE_NOT_CONFIGURED',
    }), 503


@billing_bp.delete('/me/subscription/pending')
@login_required
def cancel_pending_subscription():
    user = request.current_user
    pending = (
        SubscriptionPayment.query.filter_by(user_id=user.id, status='pending')
        .order_by(SubscriptionPayment.created_at.desc())
        .first()
    )
    if not pending:
        return jsonify({'error': 'Aucune demande en cours'}), 404
    pending.status = 'cancelled'
    pending.resolved_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True, 'payment': pending.to_dict()})


@billing_bp.post('/me/subscription/downgrade')
@login_required
def downgrade_subscription():
    """Passage Free / tier 0 immédiat (gratuit), tracé dans l’historique."""
    user = request.current_user
    data = request.get_json(silent=True) or {}
    kind = (data.get('kind') or '').strip()
    target_tier = data.get('target_tier', 0)

    try:
        if user.role == 'athlete' and kind in ('athlete_free', ''):
            kind = 'athlete_free'
            apply_subscription_change(user, kind)
            target_tier = None
        elif user.role == 'coach' and kind in ('coach_tier', ''):
            kind = 'coach_tier'
            target_tier = int(target_tier if target_tier is not None else 0)
            if target_tier != 0:
                return jsonify({'error': 'Downgrade libre uniquement vers niveau 0. Pour upgrader, passe par Stripe.'}), 400
            apply_subscription_change(user, kind, 0)
            try:
                from app.mobile_api import _enforce_coach_quota_or_trim
                _enforce_coach_quota_or_trim(user)
            except Exception:
                pass
        else:
            return jsonify({'error': 'Downgrade non applicable'}), 400
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    pay = SubscriptionPayment(
        user_id=user.id,
        kind=kind,
        target_tier=target_tier if kind == 'coach_tier' else None,
        amount_euros=0.0,
        billing_period='monthly',
        source='user_downgrade',
        status='paid',
        note='Downgrade utilisateur (gratuit)',
        resolved_at=datetime.utcnow(),
    )
    db.session.add(pay)
    db.session.commit()
    return jsonify({'ok': True, 'payment': pay.to_dict(), 'user': user.to_dict()})


@billing_bp.post('/billing/webhook')
def stripe_webhook():
    payload = request.get_data()
    sig = request.headers.get('Stripe-Signature', '')
    secret = (current_app.config.get('STRIPE_WEBHOOK_SECRET') or '').strip()
    if not _stripe_ready():
        return jsonify({'error': 'Paiement indisponible pour le moment.'}), 503

    if secret:
        try:
            event = stripe.Webhook.construct_event(payload, sig, secret)
        except Exception as e:
            return jsonify({'error': f'Webhook invalide : {e}'}), 400
    else:
        # Fail-closed hors développement : sans secret, refus.
        if not current_app.config.get('IS_DEVELOPMENT'):
            return jsonify({
                'error': 'STRIPE_WEBHOOK_SECRET manquant — webhook désactivé.',
                'code': 'WEBHOOK_SECRET_REQUIRED',
            }), 503
        event = request.get_json(silent=True) or {}

    etype = event.get('type') if isinstance(event, dict) else getattr(event, 'type', None)
    data_obj = event.get('data', {}).get('object', {}) if isinstance(event, dict) else event['data']['object']

    if etype in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
        session_id = data_obj.get('id') if isinstance(data_obj, dict) else data_obj['id']
        payment_status = data_obj.get('payment_status') if isinstance(data_obj, dict) else getattr(data_obj, 'payment_status', None)
        if payment_status and payment_status not in ('paid', 'no_payment_required'):
            return jsonify({'ok': True, 'skipped': True})
        pay = SubscriptionPayment.query.filter_by(stripe_session_id=session_id).first()
        if pay and pay.status != 'paid':
            try:
                pi = data_obj.get('payment_intent') if isinstance(data_obj, dict) else getattr(data_obj, 'payment_intent', None)
                _fulfill_payment(pay, payment_intent=pi)
                db.session.commit()
            except Exception:
                db.session.rollback()
                raise
    return jsonify({'ok': True})


@billing_bp.get('/billing/return')
def billing_return_page():
    """Page web après Checkout (ouvre l’app via deep link si possible)."""
    raw_status = (request.args.get('status') or 'success').strip().lower()
    status = raw_status if raw_status in ('success', 'cancel') else 'success'
    session_id = (request.args.get('session_id') or '').strip()
    # Autorise uniquement un id Checkout Stripe-like (cs_…)
    if session_id and not re.fullmatch(r'cs_[\w\-]+', session_id):
        session_id = ''
    deep = f'farmness://subscription?status={status}'
    if session_id:
        deep += f'&session_id={session_id}'
    deep_esc = html_lib.escape(deep, quote=True)
    title = 'Paiement reçu' if status == 'success' else 'Paiement annulé'
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Farmness</title>
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <style>body{{font-family:system-ui;background:#0D0F12;color:#fff;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:24px;text-align:center}}
    a{{color:#5EEAD4}}</style></head><body>
    <div><h1>{title}</h1>
    <p>Tu peux revenir dans l’application Farmness.</p>
    <p><a href="{deep_esc}">Ouvrir Farmness</a></p>
    <script>setTimeout(function(){{window.location={json.dumps(deep)};}},400);</script>
    </div></body></html>"""
    return html, 200, {'Content-Type': 'text/html; charset=utf-8'}


@billing_bp.get('/admin/payments')
@admin_required
def list_payments():
    status = (request.args.get('status') or '').strip()
    source = (request.args.get('source') or '').strip()
    q = SubscriptionPayment.query.order_by(SubscriptionPayment.created_at.desc())
    if status:
        q = q.filter_by(status=status)
    if source:
        q = q.filter_by(source=source)
    rows = q.limit(200).all()
    return jsonify([p.to_dict() for p in rows])


@billing_bp.post('/admin/payments/<int:payment_id>/accept')
@admin_required
def accept_payment(payment_id):
    admin = request.current_user
    pay = SubscriptionPayment.query.get_or_404(payment_id)
    if pay.status != 'pending':
        return jsonify({'error': 'Cette demande n’est plus en attente'}), 400
    try:
        _fulfill_payment(pay)
        # Demande manuelle validée → classée comme passage admin
        if pay.source == 'manual_request':
            pay.source = 'admin_manual'
            pay.note = ((pay.note or 'Demande') + ' — validé admin').strip()
        pay.resolved_by_id = admin.id
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    user = User.query.get(pay.user_id)
    return jsonify({'ok': True, 'payment': pay.to_dict(), 'user': user.to_dict() if user else None})


@billing_bp.post('/admin/payments/<int:payment_id>/refuse')
@admin_required
def refuse_payment(payment_id):
    admin = request.current_user
    pay = SubscriptionPayment.query.get_or_404(payment_id)
    if pay.status != 'pending':
        return jsonify({'error': 'Cette demande n’est plus en attente'}), 400
    pay.status = 'refused'
    pay.resolved_at = datetime.utcnow()
    pay.resolved_by_id = admin.id
    pay.note = f"{(pay.note or 'Demande').rstrip()} — refusé admin"
    db.session.commit()
    return jsonify({'ok': True, 'payment': pay.to_dict()})

