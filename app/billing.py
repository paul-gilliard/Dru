"""Abonnements Stripe (Checkout test) + suivi paiements admin."""
from __future__ import annotations

from datetime import datetime

import stripe
from flask import Blueprint, current_app, jsonify, request

from app import db
from app.mobile_auth import admin_required, login_required
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
                },
                {
                    'kind': 'athlete_independent',
                    'label': 'Indépendant',
                    'price_euros': 1.99,
                    'price_label': '1,99 € / mois',
                    'blurb': 'Stats + Easy Bilan',
                    'current': independent,
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
        },
        {
            'kind': 'coach_tier',
            'target_tier': 1,
            'label': COACH_TIER_LABELS[1],
            'price_euros': 9.99,
            'price_label': '9,99 € / mois',
            'blurb': 'Jusqu’à 3 athlètes',
            'current': tier == 1,
        },
        {
            'kind': 'coach_tier',
            'target_tier': 2,
            'label': COACH_TIER_LABELS[2],
            'price_euros': 24.99,
            'price_label': '24,99 € / mois',
            'blurb': 'Jusqu’à 10 athlètes',
            'current': tier == 2,
        },
        {
            'kind': 'coach_tier',
            'target_tier': 3,
            'label': COACH_TIER_LABELS[3],
            'price_euros': 49.99,
            'price_label': '49,99 € / mois',
            'blurb': 'Athlètes illimités',
            'current': tier == 3,
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


@billing_bp.get('/me/subscription')
@login_required
def get_my_subscription():
    user = request.current_user
    if user.role not in ('athlete', 'coach'):
        return jsonify({'error': 'Réservé athlète / coach'}), 403
    history = (
        SubscriptionPayment.query.filter_by(user_id=user.id)
        .order_by(SubscriptionPayment.created_at.desc())
        .limit(20)
        .all()
    )
    pending = next((p for p in history if p.status == 'pending'), None)
    return jsonify({
        'current': _current_plan_payload(user),
        'pending': pending.to_dict() if pending else None,
        'history': [p.to_dict() for p in history],
        'stripe_configured': bool((current_app.config.get('STRIPE_SECRET_KEY') or '').strip()),
        'test_card_hint': 'Carte test Stripe : 4242 4242 4242 4242 — date future — CVC quelconque',
    })


@billing_bp.post('/me/subscription/checkout')
@login_required
def create_checkout():
    """Crée une session Stripe Checkout (mode test). Paiement OK → upgrade auto."""
    user = request.current_user
    if user.role not in ('athlete', 'coach'):
        return jsonify({'error': 'Réservé athlète / coach'}), 403
    if not _stripe_ready():
        return jsonify({
            'error': 'Stripe non configuré (STRIPE_SECRET_KEY manquant côté serveur).',
            'code': 'STRIPE_NOT_CONFIGURED',
        }), 503

    data = request.get_json(silent=True) or {}
    kind = (data.get('kind') or '').strip()
    target_tier = data.get('target_tier')
    success_url = (data.get('success_url') or '').strip()
    cancel_url = (data.get('cancel_url') or '').strip()

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

    # Annule les pending Stripe précédents
    SubscriptionPayment.query.filter_by(
        user_id=user.id, status='pending', source='stripe',
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
        session = stripe.checkout.Session.create(
            mode='payment',
            payment_method_types=['card'],
            line_items=[{
                'quantity': 1,
                'price_data': {
                    'currency': 'eur',
                    'unit_amount': cents,
                    'product_data': {
                        'name': product_name,
                        'description': 'Abonnement mensuel Farmness (paiement test Stripe)',
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
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Stripe Checkout impossible : {e}'}), 502

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
        return jsonify({'error': 'Stripe non configuré', 'code': 'STRIPE_NOT_CONFIGURED'}), 503
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
        return jsonify({'error': f'Session Stripe invalide : {e}'}), 502

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


@billing_bp.post('/me/subscription')
@login_required
def request_subscription():
    """Crée une demande pending (si Stripe off) ou oriente vers checkout.
    Downgrade free/tier0 → appliqué tout de suite.
    """
    user = request.current_user
    if user.role not in ('athlete', 'coach'):
        return jsonify({'error': 'Réservé athlète / coach'}), 403
    data = request.get_json(silent=True) or {}
    kind = (data.get('kind') or '').strip()
    target_tier = data.get('target_tier')

    # Downgrades gratuits
    if kind == 'athlete_free' or (kind == 'coach_tier' and int(target_tier or 0) == 0):
        return downgrade_subscription()

    if kind == 'athlete_independent':
        if user.role != 'athlete':
            return jsonify({'error': 'Réservé athlète'}), 403
        if user.independent_module:
            return jsonify({'error': 'Tu es déjà en Indépendant'}), 400
        target_tier = None
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

    # Stripe dispo → le client doit utiliser /checkout (upgrade auto)
    if _stripe_ready():
        return jsonify({
            'error': 'Utilise le paiement Stripe pour upgrader.',
            'code': 'USE_STRIPE_CHECKOUT',
            'stripe_configured': True,
        }), 409

    # Une seule pending à la fois
    SubscriptionPayment.query.filter_by(
        user_id=user.id, status='pending',
    ).update({'status': 'cancelled', 'resolved_at': datetime.utcnow()}, synchronize_session=False)

    pay = SubscriptionPayment(
        user_id=user.id,
        kind=kind,
        target_tier=target_tier,
        amount_euros=_amount_euros(kind, target_tier),
        billing_period='monthly',
        source='manual_request',
        status='pending',
        note=f'Demande {_plan_label(kind, target_tier)} — en attente validation admin',
    )
    db.session.add(pay)
    db.session.commit()
    return jsonify({'ok': True, 'payment': pay.to_dict(), 'pending': True}), 201


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
        return jsonify({'error': 'Stripe non configuré'}), 503

    if secret:
        try:
            event = stripe.Webhook.construct_event(payload, sig, secret)
        except Exception as e:
            return jsonify({'error': f'Webhook invalide : {e}'}), 400
    else:
        # Mode dégradé sans secret (dev) — parse JSON brut
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
    status = request.args.get('status', 'success')
    session_id = request.args.get('session_id', '')
    deep = f'farmness://subscription?status={status}'
    if session_id:
        deep += f'&session_id={session_id}'
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Farmness</title>
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <style>body{{font-family:system-ui;background:#0D0F12;color:#fff;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:24px;text-align:center}}
    a{{color:#5EEAD4}}</style></head><body>
    <div><h1>{'Paiement reçu' if status == 'success' else 'Paiement annulé'}</h1>
    <p>Tu peux revenir dans l’application Farmness.</p>
    <p><a href="{deep}">Ouvrir Farmness</a></p>
    <script>setTimeout(function(){{window.location="{deep}"}},400);</script>
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
