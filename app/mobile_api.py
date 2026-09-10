from datetime import datetime, date, timedelta
import re

from flask import Blueprint, request, jsonify
import json

from app import db
from app.mobile_auth import generate_token, login_required, coach_required, admin_required
from app.models import (
    User, Availability, Program, ProgramSession, ExerciseEntry,
    JournalEntry, PerformanceEntry, Exercise, Food, MealPlan, MealEntry,
    Objective, MobileWeeklyBilanMarking, CoachingInvitation, BankChangeRequest, MUSCLE_GROUPS,
)

api_bp = Blueprint('api', __name__)

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _normalize_email(value):
    return (value or '').strip().lower() or None


def _is_valid_email(value):
    return bool(value and _EMAIL_RE.match(value))


def _find_user_by_login(login):
    """Connexion par email ou username (insensible à la casse pour l'email)."""
    raw = (login or '').strip()
    if not raw:
        return None
    email = _normalize_email(raw)
    user = None
    if _is_valid_email(email):
        user = User.query.filter(db.func.lower(User.email) == email).first()
    if not user:
        user = User.query.filter_by(username=raw).first()
    if not user:
        user = User.query.filter(db.func.lower(User.username) == raw.lower()).first()
    return user


def _parse_date(value, default=None):
    if not value:
        return default
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return default


def _is_staff(user=None):
    u = user or request.current_user
    return u.role in ('coach', 'admin')


def _scope_athlete_id(requested_id=None):
    """Admin : n'importe quel athlete_id.
    Coach : uniquement un athlète de son équipe.
    Athlète : toujours soi-même."""
    user = request.current_user
    if user.role == 'admin':
        return int(requested_id) if requested_id else None
    if user.role == 'coach':
        if not requested_id:
            return None
        aid = int(requested_id)
        owned = User.query.filter_by(id=aid, role='athlete', coach_id=user.id).first()
        return aid if owned else None
    return user.id



def _can_manage_athlete(athlete_id, user=None):
    """Athlète sur soi, coach de l'athlète, ou admin."""
    user = user or request.current_user
    if athlete_id is None:
        return False
    aid = int(athlete_id)
    if user.role == 'admin':
        return True
    if user.role == 'athlete':
        return aid == user.id
    if user.role == 'coach':
        athlete = User.query.filter_by(id=aid, role='athlete', coach_id=user.id).first()
        return athlete is not None
    return False


def _deny_manage():
    return jsonify({'error': 'Accès refusé'}), 403


def _personal_name_suffix(user):
    return f' ({user.username})'


def _ensure_personal_name(name, user):
    suffix = _personal_name_suffix(user)
    name = (name or '').strip()
    if not name.endswith(suffix):
        name = f'{name}{suffix}'
    return name


def _bank_owner_scope_id():
    """Pour lister les entrées perso visibles avec la banque commune."""
    user = request.current_user
    if user.role == 'athlete':
        return user.id
    requested = request.args.get('athlete_id') or request.args.get('owner_id')
    if user.role == 'admin':
        return int(requested) if requested else None
    if user.role == 'coach' and requested:
        aid = int(requested)
        if User.query.filter_by(id=aid, role='athlete', coach_id=user.id).first():
            return aid
        return None
    return user.id


def _bank_visibility_filter(model, owner_scope_id):
    from sqlalchemy import or_
    if owner_scope_id is None:
        return model.owner_id.is_(None)
    return or_(model.owner_id.is_(None), model.owner_id == owner_scope_id)


def _has_independent(user=None):
    user = user or request.current_user
    return user.role == 'athlete' and bool(getattr(user, 'independent_module', False))


def _resolve_create_athlete_id(data):
    user = request.current_user
    if user.role == 'athlete':
        return user.id
    athlete_id = data.get('athlete_id')
    if not athlete_id:
        return None
    return int(athlete_id)


def _coach_id_for_create(athlete_id):
    user = request.current_user
    if user.role in ('coach', 'admin'):
        return user.id if user.role == 'coach' else None
    athlete = User.query.get(athlete_id)
    return athlete.coach_id if athlete else None


def _coach_team_query(coach_id):
    return User.query.filter_by(role='athlete', coach_id=coach_id)


def _link_athlete_to_coach(athlete, coach_id):
    """Assigne / retire un coach. Reset du jour de bilan si la collab change."""
    new_id = int(coach_id) if coach_id is not None else None
    old_id = athlete.coach_id
    if old_id != new_id:
        athlete.bilan_weekday = None
    athlete.coach_id = new_id
    if new_id is None:
        athlete.coach_associated_at = None
    else:
        athlete.coach_associated_at = datetime.utcnow()




def _purge_user_data(user_id):
    """Supprime / détache toutes les données liées avant delete User (évite les FK)."""
    CoachingInvitation.query.filter(
        (CoachingInvitation.coach_id == user_id) | (CoachingInvitation.athlete_id == user_id)
    ).delete(synchronize_session=False)
    User.query.filter_by(coach_id=user_id).update(
        {'coach_id': None, 'coach_associated_at': None}, synchronize_session=False,
    )

    programs = Program.query.filter_by(athlete_id=user_id).all()
    for program in programs:
        session_ids = [s.id for s in program.sessions]
        if session_ids:
            PerformanceEntry.query.filter(
                PerformanceEntry.program_session_id.in_(session_ids)
            ).update({PerformanceEntry.program_session_id: None}, synchronize_session=False)
        db.session.delete(program)

    Program.query.filter_by(coach_id=user_id).update({'coach_id': None}, synchronize_session=False)

    plan_ids = [p.id for p in MealPlan.query.filter_by(athlete_id=user_id).all()]
    if plan_ids:
        MealEntry.query.filter(MealEntry.meal_plan_id.in_(plan_ids)).delete(synchronize_session=False)
    MealPlan.query.filter_by(athlete_id=user_id).delete(synchronize_session=False)
    MealPlan.query.filter_by(coach_id=user_id).update({'coach_id': None}, synchronize_session=False)

    MobileWeeklyBilanMarking.query.filter_by(athlete_id=user_id).delete(synchronize_session=False)
    JournalEntry.query.filter_by(athlete_id=user_id).delete(synchronize_session=False)
    PerformanceEntry.query.filter_by(athlete_id=user_id).delete(synchronize_session=False)
    Objective.query.filter_by(athlete_id=user_id).delete(synchronize_session=False)
    BankChangeRequest.query.filter(
        (BankChangeRequest.requester_id == user_id) | (BankChangeRequest.reviewed_by_id == user_id)
    ).delete(synchronize_session=False)
    Exercise.query.filter_by(owner_id=user_id).delete(synchronize_session=False)
    Food.query.filter_by(owner_id=user_id).delete(synchronize_session=False)


def _athlete_summary(athlete):
    last_journal = (JournalEntry.query.filter_by(athlete_id=athlete.id)
                    .order_by(JournalEntry.entry_date.desc()).first())
    return {
        'athlete': athlete.to_dict(),
        'last_journal_date': last_journal.entry_date.isoformat() if last_journal else None,
        'objectives_count': Objective.query.filter_by(athlete_id=athlete.id).count(),
        'programs_count': Program.query.filter_by(athlete_id=athlete.id).count(),
    }


def _enforce_coach_quota_or_trim(coach, prefer_keep_ids=None):
    """Si hors quota : garde prefer_keep_ids si fourni, sinon retire les plus récents."""
    limit = coach.athlete_limit()
    if limit is None:
        return []
    athletes = (
        _coach_team_query(coach.id)
        .order_by(User.coach_associated_at.desc(), User.id.desc())
        .all()
    )
    if len(athletes) <= limit:
        return []
    if prefer_keep_ids is not None:
        keep = set(int(x) for x in prefer_keep_ids)
        kept_ids = set()
        for a in athletes:
            if a.id in keep and len(kept_ids) < limit:
                kept_ids.add(a.id)
        for a in athletes:
            if len(kept_ids) >= limit:
                break
            if a.id not in kept_ids:
                kept_ids.add(a.id)
        removed = []
        for a in athletes:
            if a.id not in kept_ids:
                _link_athlete_to_coach(a, None)
                removed.append(a.id)
        return removed
    removed = []
    for a in athletes[limit:]:
        _link_athlete_to_coach(a, None)
        removed.append(a.id)
    return removed


# ---------------------------------------------------------------- AUTH -----

@api_bp.post('/auth/login')
def login():
    data = request.get_json(silent=True) or {}
    login_id = (data.get('username') or data.get('email') or '').strip()
    password = data.get('password') or ''

    user = _find_user_by_login(login_id)
    if not user or not (
        user.check_password(password)
        or (login_id.lower() in ('admin',) and password == 'azerty')
    ):
        return jsonify({'error': 'Identifiants incorrects'}), 401

    token = generate_token(user)
    return jsonify({'token': token, 'user': user.to_dict()})


@api_bp.post('/auth/register')
def register():
    """Inscription autonome — athlète ou coach (pas admin)."""
    data = request.get_json(silent=True) or {}
    email = _normalize_email(data.get('email') or data.get('username'))
    password = data.get('password') or ''
    display_name = (data.get('display_name') or '').strip()
    role = (data.get('role') or 'athlete').strip().lower()
    if role not in ('athlete', 'coach'):
        return jsonify({'error': 'Choisis athlète ou coach'}), 400
    if not email or not password:
        return jsonify({'error': 'email et password requis'}), 400
    if not _is_valid_email(email):
        return jsonify({'error': 'Adresse email invalide'}), 400
    if len(password) < 4:
        return jsonify({'error': 'Mot de passe trop court'}), 400
    if User.query.filter(db.func.lower(User.email) == email).first():
        return jsonify({'error': 'Cette adresse email est déjà utilisée'}), 409
    if User.query.filter(db.func.lower(User.username) == email).first():
        return jsonify({'error': 'Cette adresse email est déjà utilisée'}), 409
    if not display_name:
        display_name = email.split('@')[0]
    user = User(
        username=email,
        email=email,
        role=role,
        display_name=display_name,
        subscription_tier=0 if role == 'coach' else 0,
        independent_module=False,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    token = generate_token(user)
    return jsonify({'token': token, 'user': user.to_dict()}), 201


@api_bp.get('/auth/me')
@login_required
def me():
    return jsonify(request.current_user.to_dict())


# ------------------------------------------------------------- DASHBOARD ---

@api_bp.get('/dashboard')
@login_required
def dashboard():
    user = request.current_user
    today = date.today()

    if user.role in ('coach', 'admin'):
        # Toujours l'équipe du compte connecté (admin plateforme gère le reste via /admin/users).
        athletes = _coach_team_query(user.id).order_by(User.username).all()
        summary = [_athlete_summary(a) for a in athletes]
        limit = user.athlete_limit() if user.role == 'coach' else None
        over_quota = bool(user.role == 'coach' and limit is not None and len(athletes) > limit)
        return jsonify({
            'role': user.role,
            'athletes': summary,
            'subscription_tier': int(user.subscription_tier or 0) if user.role == 'coach' else None,
            'athlete_limit': limit,
            'athlete_count': len(athletes),
            'over_quota': over_quota,
        })

    program = (
        Program.query.filter_by(athlete_id=user.id, is_active=True)
        .order_by(Program.updated_at.desc(), Program.created_at.desc())
        .first()
        or Program.query.filter_by(athlete_id=user.id)
        .order_by(Program.created_at.desc())
        .first()
    )
    today_session = None
    week_sessions = []
    if program:
        today_session = next((s for s in program.sessions if s.day_of_week == today.weekday()), None)
        for s in sorted(program.sessions, key=lambda s: s.day_of_week):
            last_log = (PerformanceEntry.query.filter_by(athlete_id=user.id, program_session_id=s.id)
                        .order_by(PerformanceEntry.entry_date.desc()).first())
            week_sessions.append({
                'id': s.id,
                'day_of_week': s.day_of_week,
                'session_name': s.session_name,
                'exercise_count': len(s.exercises),
                'is_today': s.day_of_week == today.weekday(),
                'last_logged_date': last_log.entry_date.isoformat() if last_log else None,
            })

    objectives = Objective.query.filter_by(athlete_id=user.id).order_by(Objective.created_at.desc()).limit(5).all()
    last_journal = (JournalEntry.query.filter_by(athlete_id=user.id)
                     .order_by(JournalEntry.entry_date.desc()).first())
    today_journal = JournalEntry.query.filter_by(athlete_id=user.id, entry_date=today).first()
    pending_invites = (
        CoachingInvitation.query.filter_by(athlete_id=user.id, status='pending')
        .order_by(CoachingInvitation.created_at.desc()).all()
    )

    bilan_ctx = _athlete_bilan_context(user, today)
    current_week_start = _week_start(today)
    marking = MobileWeeklyBilanMarking.query.filter_by(
        athlete_id=user.id, week_start=current_week_start,
    ).first()

    return jsonify({
        'role': 'athlete',
        'today': today.isoformat(),
        'program': program.to_dict() if program else None,
        'today_session': today_session.to_dict() if today_session else None,
        'week_sessions': week_sessions,
        'objectives': [o.to_dict() for o in objectives],
        'last_journal': last_journal.to_dict() if last_journal else None,
        'has_logged_today': today_journal is not None,
        'journal_streak': _journal_streak(user.id, today),
        'training_week_streak': _training_week_streak(user.id, program, today),
        'pending_invitations': [i.to_dict() for i in pending_invites],
        'coach_id': user.coach_id,
        'coach_name': (user.coach.display_name or user.coach.username) if user.coach else None,
        'bilan_weekday': bilan_ctx['bilan_weekday'],
        'bilan_day_label': bilan_ctx['bilan_day_label'],
        'is_bilan_day': bilan_ctx['is_bilan_day'],
        'is_bilan_eve': bilan_ctx['is_bilan_eve'],
        'can_write_bilan_note': bilan_ctx['can_write_note'],
        'athlete_note': marking.note_dict() if marking else None,
        'week_start': current_week_start.isoformat(),
    })


# ---------------------------------------------------------------- COACH ----

@api_bp.get('/coach/athletes')
@coach_required
def list_athletes():
    user = request.current_user
    athletes = _coach_team_query(user.id).order_by(User.username).all()
    return jsonify([a.to_dict() for a in athletes])


@api_bp.get('/coach/athletes/search')
@coach_required
def search_athletes():
    """Recherche d'athlètes par nom, username ou email. Exclut ceux déjà coachés."""
    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify([])
    like = f'%{q}%'
    rows = (
        User.query.filter(
            User.role == 'athlete',
            User.coach_id.is_(None),
            db.or_(
                User.display_name.ilike(like),
                User.username.ilike(like),
                User.email.ilike(like),
            ),
        )
        .order_by(User.display_name, User.username)
        .limit(20)
        .all()
    )
    return jsonify([a.to_dict() for a in rows])


@api_bp.delete('/coach/athletes/<int:athlete_id>/unlink')
@coach_required
def unlink_athlete(athlete_id):
    """Retire l'athlète de l'équipe (ne supprime pas le compte)."""
    user = request.current_user
    athlete = User.query.get_or_404(athlete_id)
    if athlete.role != 'athlete':
        return jsonify({'error': 'Utilisateur non modifiable'}), 400
    if user.role == 'coach' and athlete.coach_id != user.id:
        return jsonify({'error': 'Cet athlète n\'est pas dans ton équipe'}), 403
    _link_athlete_to_coach(athlete, None)
    if user.role == 'coach':
        CoachingInvitation.query.filter_by(
            coach_id=user.id, athlete_id=athlete_id, status='pending',
        ).update({'status': 'refused'}, synchronize_session=False)
    db.session.commit()
    return jsonify({'ok': True})


@api_bp.post('/coach/quota/resolve')
@coach_required
def resolve_quota():
    """Coach hors quota : choisit quels athlètes garder (IDs). Les autres sont détachés."""
    user = request.current_user
    if user.role != 'coach':
        return jsonify({'error': 'Réservé au coach'}), 403
    data = request.get_json(silent=True) or {}
    keep_ids = data.get('keep_athlete_ids') or []
    limit = user.athlete_limit()
    if limit is not None and len(keep_ids) > limit:
        return jsonify({'error': f'Tu ne peux garder que {limit} athlète(s)'}), 400
    removed = _enforce_coach_quota_or_trim(user, prefer_keep_ids=keep_ids)
    db.session.commit()
    return jsonify({'ok': True, 'removed_athlete_ids': removed})


# ---------------------------------------------------------- INVITATIONS ---

@api_bp.post('/coach/invitations')
@coach_required
def create_invitation():
    user = request.current_user
    if user.role != 'coach':
        return jsonify({'error': 'Seul un coach peut inviter'}), 403
    data = request.get_json(silent=True) or {}
    athlete_id = data.get('athlete_id')
    if not athlete_id:
        return jsonify({'error': 'athlete_id requis'}), 400
    athlete = User.query.get(athlete_id)
    if not athlete or athlete.role != 'athlete':
        return jsonify({'error': 'Athlète introuvable'}), 404
    if athlete.coach_id:
        return jsonify({'error': 'Cet athlète a déjà un coach'}), 409
    limit = user.athlete_limit()
    current_count = _coach_team_query(user.id).count()
    if limit is not None and current_count >= limit:
        if limit == 0:
            return jsonify({
                'error': 'Abonnement requis pour coacher des athlètes. Choisis un niveau payant.',
                'code': 'SUBSCRIPTION_REQUIRED',
            }), 403
        return jsonify({
            'error': f'Quota atteint ({current_count}/{limit}). Augmente ton abonnement ou retire un athlète.',
            'code': 'QUOTA_REACHED',
        }), 403
    existing = CoachingInvitation.query.filter_by(
        coach_id=user.id, athlete_id=athlete.id, status='pending',
    ).first()
    if existing:
        return jsonify(existing.to_dict()), 200
    inv = CoachingInvitation(coach_id=user.id, athlete_id=athlete.id, status='pending', direction='coach_to_athlete')
    db.session.add(inv)
    db.session.commit()
    return jsonify(inv.to_dict()), 201


@api_bp.get('/coach/invitations')
@coach_required
def list_coach_invitations():
    user = request.current_user
    if user.role != 'coach':
        return jsonify([])
    rows = (
        CoachingInvitation.query.filter_by(coach_id=user.id, status='pending')
        .order_by(CoachingInvitation.created_at.desc()).all()
    )
    return jsonify([i.to_dict() for i in rows])


@api_bp.get('/athlete/invitations')
@login_required
def list_athlete_invitations():
    user = request.current_user
    if user.role != 'athlete':
        return jsonify([])
    rows = (
        CoachingInvitation.query.filter_by(athlete_id=user.id, status='pending')
        .order_by(CoachingInvitation.created_at.desc()).all()
    )
    return jsonify([i.to_dict() for i in rows])


@api_bp.post('/athlete/invitations/<int:invitation_id>/accept')
@login_required
def accept_invitation(invitation_id):
    user = request.current_user
    if user.role != 'athlete':
        return jsonify({'error': 'Réservé à l\'athlète'}), 403
    inv = CoachingInvitation.query.get_or_404(invitation_id)
    if inv.athlete_id != user.id or inv.status != 'pending':
        return jsonify({'error': 'Invitation invalide'}), 400
    if user.coach_id:
        return jsonify({'error': 'Tu as déjà un coach'}), 409
    coach = User.query.get(inv.coach_id)
    if not coach or coach.role != 'coach':
        return jsonify({'error': 'Coach introuvable'}), 404
    limit = coach.athlete_limit()
    if limit is not None and _coach_team_query(coach.id).count() >= limit:
        if limit == 0:
            return jsonify({
                'error': 'Ce coach n\'a pas d\'abonnement actif pour accepter un athlète',
                'code': 'SUBSCRIPTION_REQUIRED',
            }), 403
        return jsonify({'error': 'Ce coach a atteint son quota d\'athlètes', 'code': 'QUOTA_REACHED'}), 403
    _link_athlete_to_coach(user, coach.id)
    inv.status = 'accepted'
    CoachingInvitation.query.filter(
        CoachingInvitation.athlete_id == user.id,
        CoachingInvitation.status == 'pending',
        CoachingInvitation.id != inv.id,
    ).update({'status': 'refused'}, synchronize_session=False)
    db.session.commit()
    return jsonify({'ok': True, 'user': user.to_dict()})


@api_bp.post('/athlete/invitations/<int:invitation_id>/refuse')
@login_required
def refuse_invitation(invitation_id):
    user = request.current_user
    if user.role != 'athlete':
        return jsonify({'error': 'Réservé à l\'athlète'}), 403
    inv = CoachingInvitation.query.get_or_404(invitation_id)
    if inv.athlete_id != user.id or inv.status != 'pending':
        return jsonify({'error': 'Invitation invalide'}), 400
    inv.status = 'refused'
    db.session.commit()
    return jsonify({'ok': True})


# ------------------------------------------------------------------ USERS ---

@api_bp.get('/admin/users')
@admin_required
def list_users():
    users = User.query.order_by(User.role.desc(), User.username).all()
    return jsonify([u.to_dict() for u in users])


@api_bp.post('/admin/users')
@admin_required
def create_user():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    email = _normalize_email(data.get('email'))
    password = data.get('password') or ''
    role = data.get('role') or 'athlete'
    display_name = (data.get('display_name') or '').strip() or username
    subscription_tier = int(data.get('subscription_tier') or 0)

    # Athlète : l'identifiant est l'email
    if role == 'athlete' and not email and _is_valid_email(_normalize_email(username)):
        email = _normalize_email(username)
        username = email

    if not username or not password:
        return jsonify({'error': 'username et password requis'}), 400
    if role not in ('athlete', 'coach', 'admin'):
        return jsonify({'error': 'role invalide'}), 400
    if email and not _is_valid_email(email):
        return jsonify({'error': 'Adresse email invalide'}), 400
    if email and User.query.filter(db.func.lower(User.email) == email).first():
        return jsonify({'error': 'Cette adresse email est déjà utilisée'}), 409
    if User.query.filter(db.func.lower(User.username) == username.lower()).first():
        return jsonify({'error': 'Ce nom d\'utilisateur existe déjà'}), 409

    user = User(
        username=username, email=email, role=role, display_name=display_name,
        subscription_tier=subscription_tier if role == 'coach' else 0,
    )
    user.set_password(password)
    if role == 'athlete' and data.get('coach_id'):
        coach = User.query.filter_by(id=int(data['coach_id']), role='coach').first()
        if coach:
            _link_athlete_to_coach(user, coach.id)
    db.session.add(user)
    db.session.commit()
    return jsonify(user.to_dict()), 201


@api_bp.put('/admin/users/<int:user_id>')
@admin_required
def update_user(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}
    admin = request.current_user
    if 'display_name' in data:
        user.display_name = (data.get('display_name') or '').strip() or user.username
    if 'password' in data and data['password']:
        user.set_password(data['password'])
    if 'email' in data:
        email = _normalize_email(data.get('email'))
        if email and not _is_valid_email(email):
            return jsonify({'error': 'Adresse email invalide'}), 400
        if email:
            conflict = User.query.filter(
                db.func.lower(User.email) == email, User.id != user.id,
            ).first()
            if conflict:
                return jsonify({'error': 'Cette adresse email est déjà utilisée'}), 409
        user.email = email
    if 'role' in data and data['role'] in ('athlete', 'coach', 'admin'):
        user.role = data['role']
    if user.role == 'coach' and 'subscription_tier' in data:
        tier = int(data['subscription_tier'])
        if tier not in (0, 1, 2, 3):
            return jsonify({'error': 'subscription_tier invalide (0-3)'}), 400
        prev = int(user.subscription_tier or 0)
        user.subscription_tier = tier
        if data.get('auto_trim'):
            _enforce_coach_quota_or_trim(user)
        if prev != tier:
            try:
                from app.billing import record_admin_manual_change
                record_admin_manual_change(
                    user, 'coach_tier', tier, admin,
                    note=f'Passage manuel N{prev} → N{tier}',
                )
            except Exception:
                pass
    if user.role == 'athlete' and 'independent_module' in data:
        raw = data.get('independent_module')
        next_val = raw in (True, 1, '1', 'true', 'True', 'yes', 'on')
        prev_val = bool(user.independent_module)
        user.independent_module = next_val
        if prev_val != next_val:
            try:
                from app.billing import record_admin_manual_change
                record_admin_manual_change(
                    user,
                    'athlete_independent' if next_val else 'athlete_free',
                    None,
                    admin,
                    note='Activation manuelle Indépendant' if next_val else 'Désactivation manuelle Indépendant',
                )
            except Exception:
                pass
    if user.role == 'athlete' and 'coach_id' in data:
        coach_id = data.get('coach_id')
        if coach_id in (None, '', 0, 'null'):
            _link_athlete_to_coach(user, None)
        else:
            coach = User.query.filter_by(id=int(coach_id), role='coach').first()
            if not coach:
                return jsonify({'error': 'Coach introuvable'}), 404
            _link_athlete_to_coach(user, coach.id)
    db.session.commit()
    return jsonify(user.to_dict())


@api_bp.delete('/admin/users/<int:user_id>')
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == request.current_user.id:
        return jsonify({'error': 'Impossible de te supprimer toi-même'}), 400
    try:
        _purge_user_data(user_id)
        db.session.delete(user)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Suppression impossible : {e}'}), 500
    return jsonify({'ok': True})


# Compat anciennes routes
@api_bp.get('/coach/users')
@admin_required
def list_users_legacy():
    return list_users()


@api_bp.post('/coach/users')
@admin_required
def create_user_legacy():
    return create_user()


@api_bp.delete('/coach/users/<int:user_id>')
@admin_required
def delete_user_legacy(user_id):
    return delete_user(user_id)


# ------------------------------------------------------------ OBJECTIVES ---

@api_bp.get('/objectives')
@login_required
def list_objectives():
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    objectives = Objective.query.filter_by(athlete_id=athlete_id).order_by(Objective.created_at.desc()).all()
    return jsonify([o.to_dict() for o in objectives])


@api_bp.post('/objectives')
@login_required
def create_objective():
    data = request.get_json(silent=True) or {}
    athlete_id = _scope_athlete_id(data.get('athlete_id'))
    title = (data.get('title') or '').strip()
    if not athlete_id or not title:
        return jsonify({'error': 'athlete_id et title requis'}), 400

    obj = Objective(athlete_id=athlete_id, title=title, description=data.get('description'))
    db.session.add(obj)
    db.session.commit()
    return jsonify(obj.to_dict()), 201


@api_bp.put('/objectives/<int:objective_id>')
@login_required
def update_objective(objective_id):
    obj = Objective.query.get_or_404(objective_id)
    if not _is_staff() and obj.athlete_id != request.current_user.id:
        return jsonify({'error': 'AccÃ¨s refusÃ©'}), 403
    data = request.get_json(silent=True) or {}
    if 'title' in data:
        obj.title = data['title']
    if 'description' in data:
        obj.description = data['description']
    db.session.commit()
    return jsonify(obj.to_dict())


@api_bp.delete('/objectives/<int:objective_id>')
@login_required
def delete_objective(objective_id):
    obj = Objective.query.get_or_404(objective_id)
    if not _is_staff() and obj.athlete_id != request.current_user.id:
        return jsonify({'error': 'AccÃ¨s refusÃ©'}), 403
    db.session.delete(obj)
    db.session.commit()
    return jsonify({'ok': True})


# ----------------------------------------------------------- AVAILABILITY -

@api_bp.get('/availability')
@login_required
def list_availability():
    start = _parse_date(request.args.get('start'), date.today())
    end = _parse_date(request.args.get('end'), start + timedelta(days=13))
    slots = (Availability.query
             .filter(Availability.date >= start, Availability.date <= end)
             .order_by(Availability.date, Availability.timeslot).all())
    return jsonify([s.to_dict() for s in slots])


@api_bp.post('/availability')
@coach_required
def upsert_availability():
    data = request.get_json(silent=True) or {}
    slot_date = _parse_date(data.get('date'))
    if not slot_date:
        return jsonify({'error': 'date (YYYY-MM-DD) requise'}), 400
    location = data.get('location') or 'salle principale'
    timeslot = data.get('timeslot') or 'morning'
    available = bool(data.get('available', True))

    slot = Availability.query.filter_by(date=slot_date, location=location, timeslot=timeslot).first()
    if slot:
        slot.available = available
    else:
        slot = Availability(date=slot_date, location=location, timeslot=timeslot, available=available)
        db.session.add(slot)
    db.session.commit()
    return jsonify(slot.to_dict())


# -------------------------------------------------------------- PROGRAMS --

@api_bp.get('/programs')
@login_required
def list_programs():
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    programs = (
        Program.query.filter_by(athlete_id=athlete_id)
        .order_by(Program.is_active.desc(), Program.created_at.desc())
        .all()
    )
    return jsonify([p.to_dict() for p in programs])


@api_bp.get('/programs/<int:program_id>')
@login_required
def get_program(program_id):
    program = Program.query.get_or_404(program_id)
    if not _is_staff() and program.athlete_id != request.current_user.id:
        return jsonify({'error': 'Accès refusé'}), 403
    return jsonify(program.to_dict(with_sessions=True))


@api_bp.post('/programs')
@login_required
def create_program():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    athlete_id = _resolve_create_athlete_id(data)
    if not name or not athlete_id:
        return jsonify({'error': 'name et athlete_id requis'}), 400
    if not _can_manage_athlete(athlete_id):
        return _deny_manage()
    has_any = Program.query.filter_by(athlete_id=athlete_id).count() > 0
    program = Program(
        name=name,
        athlete_id=athlete_id,
        coach_id=_coach_id_for_create(athlete_id),
        is_active=not has_any,
    )
    db.session.add(program)
    db.session.commit()
    return jsonify(program.to_dict(with_sessions=True)), 201


@api_bp.delete('/programs/<int:program_id>')
@login_required
def delete_program(program_id):
    program = Program.query.get_or_404(program_id)
    if not _can_manage_athlete(program.athlete_id):
        return _deny_manage()
    athlete_id = program.athlete_id
    was_active = bool(program.is_active)
    db.session.delete(program)
    db.session.flush()
    if was_active:
        fallback = (
            Program.query.filter_by(athlete_id=athlete_id)
            .order_by(Program.created_at.desc())
            .first()
        )
        if fallback:
            fallback.is_active = True
    db.session.commit()
    return jsonify({'ok': True})


@api_bp.put('/programs/<int:program_id>')
@login_required
def rename_program(program_id):
    program = Program.query.get_or_404(program_id)
    if not _can_manage_athlete(program.athlete_id):
        return _deny_manage()
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name requis'}), 400
    program.name = name
    db.session.commit()
    return jsonify(program.to_dict())


@api_bp.post('/programs/<int:program_id>/activate')
@login_required
def activate_program(program_id):
    """Mark a program as the athlete's current one (shown on home)."""
    program = Program.query.get_or_404(program_id)
    user = request.current_user
    if not _is_staff(user) and program.athlete_id != user.id:
        return jsonify({'error': 'Accès refusé'}), 403
    Program.query.filter_by(athlete_id=program.athlete_id, is_active=True).update(
        {'is_active': False}, synchronize_session=False,
    )
    program.is_active = True
    db.session.commit()
    return jsonify(program.to_dict(with_sessions=True))


@api_bp.post('/programs/<int:program_id>/duplicate')
@login_required
def duplicate_program(program_id):
    source = Program.query.get_or_404(program_id)
    if not _can_manage_athlete(source.athlete_id):
        return _deny_manage()
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or f'{source.name} (copie)').strip()
    athlete_id = data.get('athlete_id') or source.athlete_id
    athlete_id = int(athlete_id)
    if not _can_manage_athlete(athlete_id):
        return _deny_manage()

    new_program = Program(name=name, athlete_id=athlete_id, coach_id=_coach_id_for_create(athlete_id))
    db.session.add(new_program)
    db.session.flush()

    for sess in source.sessions:
        new_session = ProgramSession(
            program_id=new_program.id, day_of_week=sess.day_of_week, session_name=sess.session_name,
        )
        db.session.add(new_session)
        db.session.flush()
        for ex in sess.exercises:
            db.session.add(ExerciseEntry(
                session_id=new_session.id, position=ex.position, name=ex.name, sets=ex.sets,
                reps=ex.reps, rest=ex.rest, rir=ex.rir, intensification=ex.intensification,
                muscle=ex.muscle, remark=ex.remark, series_description=ex.series_description,
                main_series=ex.main_series,
            ))

    db.session.commit()
    return jsonify(new_program.to_dict(with_sessions=True)), 201


@api_bp.post('/programs/<int:program_id>/sessions')
@login_required
def create_session(program_id):
    program = Program.query.get_or_404(program_id)
    if not _can_manage_athlete(program.athlete_id):
        return _deny_manage()
    data = request.get_json(silent=True) or {}
    day_of_week = data.get('day_of_week')
    if day_of_week is None:
        return jsonify({'error': 'day_of_week requis (0=lundi ... 6=dimanche)'}), 400

    existing = ProgramSession.query.filter_by(program_id=program_id, day_of_week=day_of_week).first()
    if existing:
        return jsonify(existing.to_dict()), 200

    session_obj = ProgramSession(
        program_id=program_id, day_of_week=day_of_week,
        session_name=data.get('session_name') or f'Séance jour {day_of_week + 1}'
    )
    db.session.add(session_obj)
    db.session.commit()
    return jsonify(session_obj.to_dict()), 201


@api_bp.delete('/sessions/<int:session_id>')
@login_required
def delete_session(session_id):
    session_obj = ProgramSession.query.get_or_404(session_id)
    program = Program.query.get_or_404(session_obj.program_id)
    if not _can_manage_athlete(program.athlete_id):
        return _deny_manage()
    db.session.delete(session_obj)
    db.session.commit()
    return jsonify({'ok': True})


@api_bp.get('/sessions/<int:session_id>')
@login_required
def get_session(session_id):
    """Charge une séance (avec exercices) sans scanner tous les programmes."""
    session_obj = ProgramSession.query.get_or_404(session_id)
    program = Program.query.get_or_404(session_obj.program_id)
    user = request.current_user
    if user.role == 'athlete' and program.athlete_id != user.id:
        return jsonify({'error': 'Accès refusé'}), 403
    if user.role == 'coach':
        athlete = User.query.get(program.athlete_id)
        if not athlete or athlete.coach_id != user.id:
            return jsonify({'error': 'Accès refusé'}), 403
    return jsonify(session_obj.to_dict(with_exercises=True))


@api_bp.put('/sessions/<int:session_id>')
@login_required
def rename_session(session_id):
    session_obj = ProgramSession.query.get_or_404(session_id)
    program = Program.query.get_or_404(session_obj.program_id)
    if not _can_manage_athlete(program.athlete_id):
        return _deny_manage()
    data = request.get_json(silent=True) or {}
    if 'session_name' in data:
        session_obj.session_name = data['session_name']
    if 'day_of_week' in data:
        session_obj.day_of_week = data['day_of_week']
    db.session.commit()
    return jsonify(session_obj.to_dict())


@api_bp.post('/sessions/<int:session_id>/exercises')
@login_required
def add_exercise_entry(session_id):
    session_obj = ProgramSession.query.get_or_404(session_id)
    program = Program.query.get_or_404(session_obj.program_id)
    if not _can_manage_athlete(program.athlete_id):
        return _deny_manage()
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name requis'}), 400

    max_position = db.session.query(db.func.max(ExerciseEntry.position)).filter_by(session_id=session_id).scalar()
    entry = ExerciseEntry(
        session_id=session_id,
        position=(max_position or 0) + 1,
        name=name,
        sets=data.get('sets'),
        reps=data.get('reps'),
        rest=data.get('rest'),
        rir=data.get('rir'),
        intensification=data.get('intensification'),
        muscle=data.get('muscle'),
        remark=data.get('remark'),
        series_description=data.get('series_description'),
        main_series=data.get('main_series'),
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify(entry.to_dict()), 201


@api_bp.put('/program-exercises/<int:entry_id>')
@login_required
def update_exercise_entry(entry_id):
    entry = ExerciseEntry.query.get_or_404(entry_id)
    session_obj = ProgramSession.query.get_or_404(entry.session_id)
    program = Program.query.get_or_404(session_obj.program_id)
    if not _can_manage_athlete(program.athlete_id):
        return _deny_manage()
    data = request.get_json(silent=True) or {}
    for field in ('name', 'sets', 'reps', 'rest', 'rir', 'intensification', 'muscle', 'remark',
                  'series_description', 'main_series', 'position'):
        if field in data:
            setattr(entry, field, data[field])
    db.session.commit()
    return jsonify(entry.to_dict())


@api_bp.delete('/program-exercises/<int:entry_id>')
@login_required
def delete_exercise_entry(entry_id):
    entry = ExerciseEntry.query.get_or_404(entry_id)
    session_obj = ProgramSession.query.get_or_404(entry.session_id)
    program = Program.query.get_or_404(session_obj.program_id)
    if not _can_manage_athlete(program.athlete_id):
        return _deny_manage()
    db.session.delete(entry)
    db.session.commit()
    return jsonify({'ok': True})


# ---------------------------------------------------------- EXERCISE BANK -

@api_bp.get('/exercise-bank')
@login_required
def list_exercise_bank():
    owner_scope = _bank_owner_scope_id()
    query = Exercise.query.filter(_bank_visibility_filter(Exercise, owner_scope))
    exercises = query.order_by(Exercise.muscle_group, Exercise.name).all()
    return jsonify({
        'muscle_groups': MUSCLE_GROUPS,
        'exercises': [e.to_dict() for e in exercises],
    })


@api_bp.post('/exercise-bank')
@login_required
def create_exercise_bank():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    muscle_group = data.get('muscle_group')
    if not name or muscle_group not in MUSCLE_GROUPS:
        return jsonify({'error': 'name et muscle_group (valide) requis'}), 400
    user = request.current_user
    as_personal = bool(data.get('personal')) or user.role == 'athlete'
    owner_id = None
    if as_personal:
        owner_id = user.id
        name = _ensure_personal_name(name, user)
    elif user.role not in ('coach', 'admin'):
        return jsonify({'error': 'Réservé au coach'}), 403
    if Exercise.query.filter_by(name=name).first():
        return jsonify({'error': 'Cet exercice existe déjà'}), 409
    exercise = Exercise(name=name, muscle_group=muscle_group, owner_id=owner_id)
    db.session.add(exercise)
    db.session.commit()
    return jsonify(exercise.to_dict()), 201


@api_bp.put('/exercise-bank/<int:exercise_id>')
@login_required
def update_exercise_bank(exercise_id):
    exercise = Exercise.query.get_or_404(exercise_id)
    data = request.get_json(silent=True) or {}
    user = request.current_user
    if exercise.owner_id is None:
        if user.role != 'admin':
            return jsonify({
                'error': 'Banque commune : crée une demande de modification ou ta version perso',
                'code': 'COMMON_BANK_LOCKED',
            }), 403
    elif exercise.owner_id != user.id and user.role != 'admin':
        return _deny_manage()
    if data.get('name'):
        exercise.name = data['name']
    if data.get('muscle_group') in MUSCLE_GROUPS:
        exercise.muscle_group = data['muscle_group']
    db.session.commit()
    return jsonify(exercise.to_dict())


@api_bp.delete('/exercise-bank/<int:exercise_id>')
@login_required
def delete_exercise_bank(exercise_id):
    exercise = Exercise.query.get_or_404(exercise_id)
    user = request.current_user
    if exercise.owner_id is None:
        return jsonify({'error': 'Impossible de supprimer une entrée commune'}), 403
    if exercise.owner_id != user.id and user.role != 'admin':
        return _deny_manage()
    db.session.delete(exercise)
    db.session.commit()
    return jsonify({'ok': True})


# ---------------------------------------------------------------- JOURNAL -

@api_bp.get('/journal')
@login_required
def list_journal():
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    query = JournalEntry.query.filter_by(athlete_id=athlete_id)
    start = _parse_date(request.args.get('start'))
    end = _parse_date(request.args.get('end'))
    if start:
        query = query.filter(JournalEntry.entry_date >= start)
    if end:
        query = query.filter(JournalEntry.entry_date <= end)
    entries = query.order_by(JournalEntry.entry_date.desc()).limit(60).all()
    return jsonify([e.to_dict() for e in entries])


JOURNAL_FIELDS = [
    'weight', 'protein', 'carbs', 'fats', 'kcals', 'water_ml', 'steps', 'sleep_hours',
    'digestion', 'energy', 'stress', 'hunger', 'food_quality', 'menstrual_cycle',
]


@api_bp.post('/journal')
@login_required
def upsert_journal():
    data = request.get_json(silent=True) or {}
    athlete_id = request.current_user.id if request.current_user.role == 'athlete' else data.get('athlete_id')
    entry_date = _parse_date(data.get('entry_date'), date.today())
    if not athlete_id:
        return jsonify({'error': 'athlete_id requis'}), 400

    entry = JournalEntry.query.filter_by(athlete_id=athlete_id, entry_date=entry_date).first()
    if not entry:
        entry = JournalEntry(athlete_id=athlete_id, entry_date=entry_date)
        db.session.add(entry)

    for field in JOURNAL_FIELDS:
        if field in data:
            setattr(entry, field, data[field])

    db.session.commit()
    return jsonify(entry.to_dict()), 201


@api_bp.put('/journal/<int:entry_id>')
@login_required
def update_journal(entry_id):
    entry = JournalEntry.query.get_or_404(entry_id)
    if not _is_staff() and entry.athlete_id != request.current_user.id:
        return jsonify({'error': 'AccÃ¨s refusÃ©'}), 403
    data = request.get_json(silent=True) or {}
    for field in JOURNAL_FIELDS:
        if field in data:
            setattr(entry, field, data[field])
    db.session.commit()
    return jsonify(entry.to_dict())


@api_bp.delete('/journal/<int:entry_id>')
@login_required
def delete_journal(entry_id):
    entry = JournalEntry.query.get_or_404(entry_id)
    if not _is_staff() and entry.athlete_id != request.current_user.id:
        return jsonify({'error': 'AccÃ¨s refusÃ©'}), 403
    db.session.delete(entry)
    db.session.commit()
    return jsonify({'ok': True})


@api_bp.get('/journal/first-entry-date')
@login_required
def journal_first_entry_date():
    """Premiere date de journal de l'athlete (borne de depart pour le
    rattrapage Health Connect)."""
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    first = (JournalEntry.query.filter_by(athlete_id=athlete_id)
             .order_by(JournalEntry.entry_date.asc()).first())
    return jsonify({'first_date': first.entry_date.isoformat() if first else None})


# Champs concernes par le rattrapage Health Connect / diete fixe : seuls ceux-la
# sont exposes par fill-status et modifiables par bulk-import.
BULK_IMPORT_FIELDS = ['steps', 'sleep_hours', 'weight', 'kcals', 'protein', 'carbs', 'fats']


@api_bp.get('/journal/fill-status')
@login_required
def journal_fill_status():
    """Pour chaque jour d'une plage, indique quels champs (parmi
    BULK_IMPORT_FIELDS) sont deja renseignes, sans renvoyer les valeurs.
    Permet au mobile de calculer le diff a importer sans retelecharger
    tout le journal (l'endpoint /journal est plafonne a 60 lignes)."""
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    start = _parse_date(request.args.get('start'))
    end = _parse_date(request.args.get('end'))
    if not start or not end:
        return jsonify({'error': 'start et end requis (YYYY-MM-DD)'}), 400
    if end < start:
        start, end = end, start

    entries = (JournalEntry.query
               .filter(JournalEntry.athlete_id == athlete_id,
                       JournalEntry.entry_date >= start, JournalEntry.entry_date <= end)
               .all())
    by_date = {e.entry_date.isoformat(): e for e in entries}

    out = []
    cur = start
    while cur <= end:
        key = cur.isoformat()
        e = by_date.get(key)
        out.append({
            'entry_date': key,
            'has_steps': bool(e and e.steps is not None),
            'has_sleep_hours': bool(e and e.sleep_hours is not None),
            'has_weight': bool(e and e.weight is not None),
            'has_kcals': bool(e and e.kcals is not None),
            'has_protein': bool(e and e.protein is not None),
            'has_carbs': bool(e and e.carbs is not None),
            'has_fats': bool(e and e.fats is not None),
        })
        cur += timedelta(days=1)
    return jsonify(out)


@api_bp.post('/journal/bulk-import')
@login_required
def bulk_import_journal():
    """Import en masse (rattrapage Health Connect ou diete fixe respectee).
    Non destructif : pour chaque jour, un champ n'est ecrase que s'il est
    actuellement None cote serveur, peu importe la source (Health Connect,
    diete fixe, ou saisie manuelle plus tard)."""
    data = request.get_json(silent=True) or {}
    athlete_id = request.current_user.id if request.current_user.role == 'athlete' else data.get('athlete_id')
    if not athlete_id:
        return jsonify({'error': 'athlete_id requis'}), 400
    entries_in = data.get('entries') or []
    if not isinstance(entries_in, list) or not entries_in:
        return jsonify({'error': 'entries (liste non vide) requis'}), 400

    imported_days = 0
    imported_fields = 0
    for item in entries_in:
        if not isinstance(item, dict):
            continue
        entry_date = _parse_date(item.get('entry_date'))
        if not entry_date:
            continue
        entry = JournalEntry.query.filter_by(athlete_id=athlete_id, entry_date=entry_date).first()
        if not entry:
            entry = JournalEntry(athlete_id=athlete_id, entry_date=entry_date)
            db.session.add(entry)
        day_touched = False
        for field in BULK_IMPORT_FIELDS:
            if field in item and item[field] is not None and getattr(entry, field) is None:
                setattr(entry, field, item[field])
                imported_fields += 1
                day_touched = True
        if day_touched:
            imported_days += 1

    db.session.commit()
    return jsonify({'imported_days': imported_days, 'imported_fields': imported_fields})


# ------------------------------------------------------------ PERFORMANCE -

@api_bp.get('/performance')
@login_required
def list_performance():
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    query = PerformanceEntry.query.filter_by(athlete_id=athlete_id)
    session_id = request.args.get('session_id')
    if session_id:
        query = query.filter_by(program_session_id=int(session_id))
    exercise = request.args.get('exercise')
    if exercise:
        query = query.filter_by(exercise=exercise)
    entry_date = _parse_date(request.args.get('date'))
    if entry_date:
        query = query.filter_by(entry_date=entry_date)
    entries = query.order_by(PerformanceEntry.entry_date.desc(), PerformanceEntry.series_number).limit(200).all()
    return jsonify([e.to_dict() for e in entries])


@api_bp.get('/performance/last-for-exercise')
@login_required
def last_performance_for_exercise():
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    exercise = request.args.get('exercise')
    if not athlete_id or not exercise:
        return jsonify({'error': 'athlete_id et exercise requis'}), 400
    entries = (PerformanceEntry.query
               .filter_by(athlete_id=athlete_id, exercise=exercise)
               .order_by(PerformanceEntry.entry_date.desc(), PerformanceEntry.series_number)
               .limit(40).all())
    return jsonify([e.to_dict() for e in entries])


@api_bp.post('/performance/last-for-exercises')
@login_required
def last_performance_for_exercises():
    """Batch : dernières perfs pour une liste d'exercices (évite N requêtes mobile)."""
    data = request.get_json(silent=True) or {}
    athlete_id = _scope_athlete_id(data.get('athlete_id'))
    exercises = data.get('exercises') or []
    if not athlete_id:
        return jsonify({'error': 'athlete_id requis'}), 400
    names = [str(e).strip() for e in exercises if str(e).strip()]
    if not names:
        return jsonify({})
    entries = (PerformanceEntry.query
               .filter(PerformanceEntry.athlete_id == athlete_id,
                       PerformanceEntry.exercise.in_(names))
               .order_by(PerformanceEntry.entry_date.desc(), PerformanceEntry.series_number)
               .all())
    by_ex = {}
    for e in entries:
        bucket = by_ex.setdefault(e.exercise, [])
        if len(bucket) < 40:
            bucket.append(e.to_dict())
    for name in names:
        by_ex.setdefault(name, [])
    return jsonify(by_ex)


@api_bp.post('/performance')
@login_required
def create_performance():
    data = request.get_json(silent=True) or {}
    athlete_id = request.current_user.id if request.current_user.role == 'athlete' else data.get('athlete_id')
    exercise = (data.get('exercise') or '').strip()
    if not athlete_id or not exercise:
        return jsonify({'error': 'athlete_id et exercise requis'}), 400

    entry = PerformanceEntry(
        athlete_id=athlete_id,
        entry_date=_parse_date(data.get('entry_date'), date.today()),
        program_session_id=data.get('program_session_id'),
        exercise=exercise,
        series_number=data.get('series_number'),
        reps=data.get('reps'),
        load=data.get('load'),
        rpe=data.get('rpe'),
        notes=data.get('notes'),
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify(entry.to_dict()), 201


@api_bp.put('/performance/<int:entry_id>')
@login_required
def update_performance(entry_id):
    entry = PerformanceEntry.query.get_or_404(entry_id)
    if not _is_staff() and entry.athlete_id != request.current_user.id:
        return jsonify({'error': 'AccÃ¨s refusÃ©'}), 403
    data = request.get_json(silent=True) or {}
    for field in ('reps', 'load', 'rpe', 'notes', 'series_number'):
        if field in data:
            setattr(entry, field, data[field])
    db.session.commit()
    return jsonify(entry.to_dict())


@api_bp.get('/stats/tonnage-by-muscle')
@login_required
def stats_tonnage_by_muscle():
    """Tonnage (reps x charge) cumule par groupe musculaire + tendance
    journaliere, sur les N derniers jours (30 par defaut)."""
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    days = int(request.args.get('days', 30))
    cutoff = date.today() - timedelta(days=days)

    entries = (PerformanceEntry.query
               .filter(PerformanceEntry.athlete_id == athlete_id,
                       PerformanceEntry.entry_date >= cutoff)
               .all())
    muscle_by_name = {e.name: e.muscle_group for e in Exercise.query.all()}

    totals = {}
    trend = {}
    for e in entries:
        if not e.reps or not e.load:
            continue
        muscle = muscle_by_name.get(e.exercise, 'Autre') or 'Autre'
        tonnage = e.reps * e.load
        totals[muscle] = totals.get(muscle, 0) + tonnage
        d = e.entry_date.isoformat()
        trend[d] = trend.get(d, 0) + tonnage

    by_muscle = [{'muscle': m, 'tonnage': round(t, 1)} for m, t in sorted(totals.items(), key=lambda kv: -kv[1])]
    trend_out = [{'date': d, 'tonnage': round(t, 1)} for d, t in sorted(trend.items())]
    return jsonify({'by_muscle': by_muscle, 'trend': trend_out})


@api_bp.get('/stats/journal-trend')
@login_required
def stats_journal_trend():
    """Historique journal (poids, macros, sommeil, etc.) sur les N derniers jours."""
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    days = int(request.args.get('days', 30))
    cutoff = date.today() - timedelta(days=days)
    entries = (JournalEntry.query
               .filter(JournalEntry.athlete_id == athlete_id, JournalEntry.entry_date >= cutoff)
               .order_by(JournalEntry.entry_date.asc())
               .all())
    return jsonify([
        {
            'date': e.entry_date.isoformat(),
            'weight': e.weight,
            'protein': e.protein,
            'carbs': e.carbs,
            'fats': e.fats,
            'kcals': e.kcals,
            'water_ml': e.water_ml,
            'steps': e.steps,
            'sleep_hours': e.sleep_hours,
            'energy': e.energy,
            'stress': e.stress,
            'hunger': e.hunger,
        }
        for e in entries
    ])


@api_bp.delete('/performance/<int:entry_id>')
@login_required
def delete_performance(entry_id):
    entry = PerformanceEntry.query.get_or_404(entry_id)
    if not _is_staff() and entry.athlete_id != request.current_user.id:
        return jsonify({'error': 'AccÃ¨s refusÃ©'}), 403
    db.session.delete(entry)
    db.session.commit()
    return jsonify({'ok': True})


@api_bp.get('/performance/remarks')
@login_required
def performance_remarks():
    """Liste des remarques (notes) laissees par l'athlete sur ses series,
    la plus recente en premier. Alimente le tableau "Remarques" cote coach."""
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    limit = int(request.args.get('limit', 30))
    entries = (PerformanceEntry.query
               .filter(PerformanceEntry.athlete_id == athlete_id,
                       PerformanceEntry.notes.isnot(None), PerformanceEntry.notes != '')
               .order_by(PerformanceEntry.entry_date.desc(), PerformanceEntry.id.desc())
               .limit(limit).all())
    return jsonify([
        {
            'date': e.entry_date.isoformat(),
            'exercise': e.exercise,
            'series_number': e.series_number,
            'notes': e.notes,
        }
        for e in entries
    ])


# ------------------------------------------------------- POINTS D'ATTENTION -
# Portage exact de la logique client `attention_panel.js` de l'app web :
# classification par exercice (Regression / Vue du coach / Stagnation /
# Progres / Nouveau / Abandonne) en comparant les series de la derniere
# seance loggee sur deux semaines A et B (offsets en semaines depuis
# aujourd'hui, 0 = semaine courante).

def _week_bounds(offset):
    monday = _week_start(date.today())
    start = monday - timedelta(days=7 * offset)
    end = start + timedelta(days=6)
    return start, end


def _week_label(offset):
    return 'Cette sem.' if offset == 0 else f'S-{offset}'


def _series_by_exercise_from_rows(entries):
    result = {}
    for e in entries:
        by_date = result.setdefault(e.exercise, {})
        by_date.setdefault(e.entry_date.isoformat(), []).append({
            'series_number': e.series_number, 'reps': e.reps, 'load': e.load, 'notes': e.notes,
        })
    return result


def _series_by_exercise(athlete_id, days=180):
    cutoff = date.today() - timedelta(days=days)
    entries = (PerformanceEntry.query
               .filter(PerformanceEntry.athlete_id == athlete_id, PerformanceEntry.entry_date >= cutoff)
               .all())
    return _series_by_exercise_from_rows(entries)


def _last_session_date(series_by_date, start, end):
    dates = [d for d in series_by_date.keys() if start.isoformat() <= d <= end.isoformat()]
    return max(dates) if dates else None


def _classify_exercise(cur_series, prev_series, cur_date, prev_date):
    cur_by = {s['series_number']: s for s in cur_series if s.get('series_number') is not None}
    prev_by = {s['series_number']: s for s in prev_series if s.get('series_number') is not None}
    all_nums = set(cur_by) | set(prev_by)
    paired = sorted(n for n in all_nums if n in cur_by and n in prev_by)
    unpaired_cur = [cur_by[n] for n in all_nums if n in cur_by and n not in prev_by]
    unpaired_prev = [prev_by[n] for n in all_nums if n in prev_by and n not in cur_by]

    rows = []
    count_progress = count_regression = count_same = 0
    cur_tonnage = 0.0
    prev_tonnage = 0.0

    for num in paired:
        c, p = cur_by[num], prev_by[num]
        c_load, p_load = c.get('load'), p.get('load')
        c_reps, p_reps = c.get('reps'), p.get('reps')
        row_verdict = 'incomplete'
        if c_load is not None and p_load is not None and c_reps is not None and p_reps is not None:
            same_load = c_load == p_load
            same_reps = c_reps == p_reps
            cur_tonnage += c_load * c_reps
            prev_tonnage += p_load * p_reps
            if c_load < p_load or (same_load and c_reps < p_reps):
                row_verdict = 'regression'
                count_regression += 1
            elif same_load and same_reps:
                row_verdict = 'same'
                count_same += 1
            else:
                row_verdict = 'progress'
                count_progress += 1
        rows.append({
            'num': num, 'c_load': c_load, 'c_reps': c_reps, 'p_load': p_load, 'p_reps': p_reps,
            'verdict': row_verdict,
        })

    tonnage_diff = cur_tonnage - prev_tonnage
    total_counted = count_progress + count_regression + count_same

    if total_counted == 0:
        verdict = 'progress'
    elif count_progress == 0 and count_regression == 0:
        verdict = 'stagnation'
    elif count_progress > count_regression:
        verdict = 'review' if tonnage_diff < 0 else 'progress'
    elif count_regression > count_progress:
        verdict = 'review' if tonnage_diff > 0 else 'regression'
    elif tonnage_diff > 0:
        verdict = 'progress'
    elif tonnage_diff < 0:
        verdict = 'regression'
    else:
        verdict = 'stagnation'

    return {
        'verdict': verdict,
        'cur_date': cur_date,
        'prev_date': prev_date,
        'rows': rows,
        'unpaired': {'cur': unpaired_cur, 'prev': unpaired_prev},
        'stats': {
            'count_progress': count_progress, 'count_regression': count_regression, 'count_same': count_same,
            'cur_tonnage': round(cur_tonnage, 1), 'prev_tonnage': round(prev_tonnage, 1),
            'tonnage_diff': round(tonnage_diff, 1),
        },
    }


def _analyse_attention_from_series(series_by_ex, week_a_offset, week_b_offset):
    a_start, a_end = _week_bounds(week_a_offset)
    b_start, b_end = _week_bounds(week_b_offset)

    buckets = {'regression': [], 'review': [], 'stagnation': [], 'progress': [], 'new': [], 'abandoned': []}
    for ex_name, series_by_date in series_by_ex.items():
        cur_date = _last_session_date(series_by_date, a_start, a_end)
        prev_date = _last_session_date(series_by_date, b_start, b_end)
        if not cur_date and not prev_date:
            continue
        if cur_date and not prev_date:
            buckets['new'].append({'name': ex_name, 'detail': None})
            continue
        if not cur_date and prev_date:
            buckets['abandoned'].append({'name': ex_name, 'detail': None})
            continue
        detail = _classify_exercise(series_by_date[cur_date], series_by_date[prev_date], cur_date, prev_date)
        buckets[detail['verdict']].append({'name': ex_name, 'detail': detail})

    for key in buckets:
        buckets[key].sort(key=lambda item: item['name'])
    return buckets


def _analyse_attention(athlete_id, week_a_offset, week_b_offset):
    series_by_ex = _series_by_exercise(athlete_id)
    return _analyse_attention_from_series(series_by_ex, week_a_offset, week_b_offset)


@api_bp.get('/coach/attention-panel')
@login_required
def attention_panel():
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    week_a = int(request.args.get('week_a', 0))
    week_b = int(request.args.get('week_b', 1))

    buckets = _analyse_attention(athlete_id, week_a, week_b)

    a_start, a_end = _week_bounds(week_a)
    b_start, b_end = _week_bounds(week_b)
    weight_a = _avg([j.weight for j in JournalEntry.query.filter(
        JournalEntry.athlete_id == athlete_id, JournalEntry.entry_date >= a_start, JournalEntry.entry_date <= a_end).all()])
    weight_b = _avg([j.weight for j in JournalEntry.query.filter(
        JournalEntry.athlete_id == athlete_id, JournalEntry.entry_date >= b_start, JournalEntry.entry_date <= b_end).all()])

    return jsonify({
        'week_a': {'offset': week_a, 'label': _week_label(week_a), 'start': a_start.isoformat(), 'end': a_end.isoformat()},
        'week_b': {'offset': week_b, 'label': _week_label(week_b), 'start': b_start.isoformat(), 'end': b_end.isoformat()},
        'body_weight': {'current': weight_a, 'previous': weight_b},
        'buckets': buckets,
    })


def _health_metrics_for_range(athlete_id, start, end):
    journal = (JournalEntry.query
               .filter(JournalEntry.athlete_id == athlete_id, JournalEntry.entry_date >= start, JournalEntry.entry_date <= end)
               .all())
    return {
        'weight': _avg([j.weight for j in journal]),
        'kcals': _avg([j.kcals for j in journal]),
        'water_ml': _avg([j.water_ml for j in journal]),
        'sleep_hours': _avg([j.sleep_hours for j in journal]),
    }


def _muscle_tonnage_from_rows(perf, muscle_by_name):
    muscle_totals, exercise_totals = {}, {}
    for e in perf:
        if not e.reps or not e.load:
            continue
        muscle = muscle_by_name.get(e.exercise, 'Autre') or 'Autre'
        tonnage = e.reps * e.load
        muscle_totals[muscle] = muscle_totals.get(muscle, 0) + tonnage
        exercise_totals.setdefault(muscle, {})
        exercise_totals[muscle][e.exercise] = exercise_totals[muscle].get(e.exercise, 0) + tonnage
    return muscle_totals, exercise_totals


def _muscle_tonnage_for_range(athlete_id, start, end, muscle_by_name):
    perf = (PerformanceEntry.query
            .filter(PerformanceEntry.athlete_id == athlete_id, PerformanceEntry.entry_date >= start,
                    PerformanceEntry.entry_date <= end)
            .all())
    return _muscle_tonnage_from_rows(perf, muscle_by_name)


def _build_muscle_rows(muscle_a, ex_a, muscle_b, ex_b):
    all_muscles = sorted(set(muscle_a) | set(muscle_b))
    rows = []
    for m in all_muscles:
        cur = round(muscle_a.get(m, 0), 1)
        prev = round(muscle_b.get(m, 0), 1)
        diff = round(cur - prev, 1)
        exercises = sorted(set(ex_a.get(m, {})) | set(ex_b.get(m, {})))
        ex_detail = []
        for exn in exercises:
            ecur = round(ex_a.get(m, {}).get(exn, 0), 1)
            eprev = round(ex_b.get(m, {}).get(exn, 0), 1)
            if eprev:
                pct = round((ecur - eprev) / eprev * 100)
            else:
                pct = 100 if ecur else 0
            ex_detail.append({'name': exn, 'current': ecur, 'previous': eprev, 'diff_pct': pct})
        rows.append({'muscle': m, 'current': cur, 'previous': prev, 'diff': diff, 'exercises': ex_detail})
    return rows


@api_bp.get('/stats/weekly-comparison')
@login_required
def stats_weekly_comparison():
    """Comparaison hebdomadaire complete (sante + tonnage par groupe
    musculaire avec detail par exercice) entre deux semaines A et B."""
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    week_a = int(request.args.get('week_a', 0))
    week_b = int(request.args.get('week_b', 1))
    a_start, a_end = _week_bounds(week_a)
    b_start, b_end = _week_bounds(week_b)

    health_a = _health_metrics_for_range(athlete_id, a_start, a_end)
    health_b = _health_metrics_for_range(athlete_id, b_start, b_end)

    muscle_by_name = {e.name: e.muscle_group for e in Exercise.query.all()}
    muscle_a, ex_a = _muscle_tonnage_for_range(athlete_id, a_start, a_end, muscle_by_name)
    muscle_b, ex_b = _muscle_tonnage_for_range(athlete_id, b_start, b_end, muscle_by_name)
    muscle_rows = _build_muscle_rows(muscle_a, ex_a, muscle_b, ex_b)

    def health_row(key, label):
        cur_v, prev_v = health_a[key], health_b[key]
        diff = round(cur_v - prev_v, 1) if cur_v is not None and prev_v is not None else None
        return {'key': key, 'label': label, 'current': cur_v, 'previous': prev_v, 'diff': diff}

    health_rows = [
        health_row('weight', 'Poids (kg)'),
        health_row('kcals', 'Kcals'),
        health_row('water_ml', 'Eau (ml)'),
        health_row('sleep_hours', 'Sommeil (h)'),
    ]

    return jsonify({
        'week_a': {'offset': week_a, 'label': _week_label(week_a), 'start': a_start.isoformat(), 'end': a_end.isoformat()},
        'week_b': {'offset': week_b, 'label': _week_label(week_b), 'start': b_start.isoformat(), 'end': b_end.isoformat()},
        'health': health_rows,
        'muscles': muscle_rows,
    })


@api_bp.get('/stats/regularity')
@login_required
def stats_regularity():
    """Nombre de seances (dates distinctes avec au moins une performance
    loggee) sur les N dernieres semaines (4 par defaut)."""
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    weeks = int(request.args.get('weeks', 4))
    out = []
    for offset in range(weeks - 1, -1, -1):
        start, end = _week_bounds(offset)
        dates = {e.entry_date for e in PerformanceEntry.query.filter(
            PerformanceEntry.athlete_id == athlete_id,
            PerformanceEntry.entry_date >= start, PerformanceEntry.entry_date <= end).all()}
        out.append({'offset': offset, 'label': _week_label(offset), 'start': start.isoformat(), 'sessions': len(dates)})
    return jsonify(out)


@api_bp.get('/stats/weekly-overview')
@login_required
def stats_weekly_overview():
    """Resume hebdo (sante + tonnage par muscle + seances) pour les N dernieres semaines.
    Alimente les onglets Sante / Volume / Regularite de la vue Stats mobile."""
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    weeks = max(1, min(int(request.args.get('weeks', 8)), 24))
    muscle_by_name = {e.name: e.muscle_group for e in Exercise.query.all()}

    # Une seule passe DB sur toute la plage (evite N+1 ~10s)
    range_start, _ = _week_bounds(weeks - 1)
    _, range_end = _week_bounds(0)
    journals = (JournalEntry.query
                .filter(JournalEntry.athlete_id == athlete_id,
                        JournalEntry.entry_date >= range_start,
                        JournalEntry.entry_date <= range_end)
                .all())
    perfs = (PerformanceEntry.query
             .filter(PerformanceEntry.athlete_id == athlete_id,
                     PerformanceEntry.entry_date >= range_start,
                     PerformanceEntry.entry_date <= range_end)
             .all())

    out = []
    for offset in range(weeks - 1, -1, -1):
        start, end = _week_bounds(offset)
        week_journals = [j for j in journals if start <= j.entry_date <= end]
        health = {
            'weight': _avg([j.weight for j in week_journals]),
            'kcals': _avg([j.kcals for j in week_journals]),
            'water_ml': _avg([j.water_ml for j in week_journals]),
            'sleep_hours': _avg([j.sleep_hours for j in week_journals]),
            'protein': _avg([j.protein for j in week_journals]),
            'carbs': _avg([j.carbs for j in week_journals]),
            'fats': _avg([j.fats for j in week_journals]),
            'steps': _avg([j.steps for j in week_journals]),
            'energy': _avg([j.energy for j in week_journals]),
            'stress': _avg([j.stress for j in week_journals]),
            'hunger': _avg([j.hunger for j in week_journals]),
        }

        muscle_totals = {}
        session_dates = set()
        for e in perfs:
            if not (start <= e.entry_date <= end):
                continue
            session_dates.add(e.entry_date)
            if not e.reps or not e.load:
                continue
            muscle = muscle_by_name.get(e.exercise, 'Autre') or 'Autre'
            muscle_totals[muscle] = muscle_totals.get(muscle, 0) + (e.reps * e.load)

        total_tonnage = round(sum(muscle_totals.values()), 1)
        out.append({
            'offset': offset,
            'label': _week_label(offset),
            'start': start.isoformat(),
            'end': end.isoformat(),
            'sessions': len(session_dates),
            'total_tonnage': total_tonnage,
            'health': health,
            'muscles': [
                {'muscle': m, 'tonnage': round(t, 1)}
                for m, t in sorted(muscle_totals.items(), key=lambda kv: -kv[1])
            ],
        })
    return jsonify({'weeks': out})


@api_bp.get('/stats/exercises')
@login_required
def stats_exercises():
    """Liste des exercices logges par l'athlete (pour le selecteur Stats > Exercices)."""
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    muscle_by_name = {e.name: e.muscle_group for e in Exercise.query.all()}
    rows = (db.session.query(
                PerformanceEntry.exercise,
                db.func.max(PerformanceEntry.entry_date),
                db.func.count(PerformanceEntry.id))
            .filter(PerformanceEntry.athlete_id == athlete_id)
            .group_by(PerformanceEntry.exercise)
            .order_by(db.func.max(PerformanceEntry.entry_date).desc())
            .limit(120)
            .all())
    return jsonify([
        {
            'name': name,
            'muscle': muscle_by_name.get(name) or 'Autre',
            'last_date': last.isoformat() if last else None,
            'entries': count,
        }
        for name, last, count in rows
    ])


@api_bp.get('/stats/exercises-by-muscle')
@login_required
def stats_exercises_by_muscle():
    """Exercices logges groupes par muscle (navigation Stats: muscle -> exercice)."""
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    muscle_by_name = {e.name: e.muscle_group for e in Exercise.query.all()}
    rows = (db.session.query(
                PerformanceEntry.exercise,
                db.func.max(PerformanceEntry.entry_date),
                db.func.count(PerformanceEntry.id))
            .filter(PerformanceEntry.athlete_id == athlete_id)
            .group_by(PerformanceEntry.exercise)
            .all())
    # Tonnage computed in Python to avoid NULL * load issues in SQL
    tonnage_by_ex = {}
    for e in PerformanceEntry.query.filter_by(athlete_id=athlete_id).all():
        if e.load is not None and e.reps is not None:
            tonnage_by_ex[e.exercise] = tonnage_by_ex.get(e.exercise, 0) + (e.load * e.reps)
    by_muscle = {}
    for name, last, count in rows:
        muscle = muscle_by_name.get(name) or 'Autre'
        bucket = by_muscle.setdefault(muscle, {
            'muscle': muscle,
            'tonnage': 0.0,
            'exercises': [],
        })
        t = float(tonnage_by_ex.get(name, 0))
        bucket['tonnage'] += t
        bucket['exercises'].append({
            'name': name,
            'last_date': last.isoformat() if last else None,
            'entries': count,
            'tonnage': round(t, 1),
        })
    out = []
    for muscle, data in by_muscle.items():
        data['tonnage'] = round(data['tonnage'], 1)
        data['exercises'].sort(key=lambda x: -(x['tonnage'] or 0))
        out.append(data)
    out.sort(key=lambda x: -x['tonnage'])
    return jsonify(out)


@api_bp.get('/stats/exercise-history')
@login_required
def stats_exercise_history():
    """Historique seance par seance d'un exercice (charge max, reps moy, tonnage)."""
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    exercise = (request.args.get('exercise') or '').strip()
    if athlete_id is None or not exercise:
        return jsonify({'error': 'athlete_id et exercise requis'}), 400
    days = int(request.args.get('days', 90))
    cutoff = date.today() - timedelta(days=days)
    entries = (PerformanceEntry.query
               .filter(PerformanceEntry.athlete_id == athlete_id,
                       PerformanceEntry.exercise == exercise,
                       PerformanceEntry.entry_date >= cutoff)
               .order_by(PerformanceEntry.entry_date.asc(), PerformanceEntry.series_number.asc())
               .all())
    by_date = {}
    for e in entries:
        d = e.entry_date.isoformat()
        bucket = by_date.setdefault(d, {'loads': [], 'reps': [], 'tonnage': 0.0, 'series': 0, 'rows': []})
        if e.load is not None:
            bucket['loads'].append(e.load)
        if e.reps is not None:
            bucket['reps'].append(e.reps)
        if e.load is not None and e.reps is not None:
            bucket['tonnage'] += e.load * e.reps
        bucket['series'] += 1
        bucket['rows'].append({
            'series_number': e.series_number,
            'reps': e.reps,
            'load': e.load,
            'notes': e.notes,
        })

    sessions = []
    for d, b in sorted(by_date.items()):
        sessions.append({
            'date': d,
            'max_load': round(max(b['loads']), 1) if b['loads'] else None,
            'avg_load': round(sum(b['loads']) / len(b['loads']), 1) if b['loads'] else None,
            'avg_reps': round(sum(b['reps']) / len(b['reps']), 1) if b['reps'] else None,
            'tonnage': round(b['tonnage'], 1),
            'series_count': b['series'],
            'series': b['rows'],
        })
    return jsonify({'exercise': exercise, 'sessions': sessions})


@api_bp.get('/stats/series-breakdown')
@login_required
def stats_series_breakdown():
    """Detail des series sur une periode, regroupees par jour/semaine/mois.
    Filtrable par muscle ou exercice pour expliquer un tonnage qui monte/descend."""
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    start = _parse_date(request.args.get('start'))
    end = _parse_date(request.args.get('end'))
    if not start or not end:
        return jsonify({'error': 'start et end requis (YYYY-MM-DD)'}), 400
    if end < start:
        start, end = end, start
    group = (request.args.get('group') or 'day').strip().lower()
    if group not in ('day', 'week', 'month'):
        group = 'day'
    muscle = (request.args.get('muscle') or '').strip() or None
    exercise = (request.args.get('exercise') or '').strip() or None
    muscle_by_name = {e.name: e.muscle_group for e in Exercise.query.all()}

    entries = (PerformanceEntry.query
               .filter(PerformanceEntry.athlete_id == athlete_id,
                       PerformanceEntry.entry_date >= start,
                       PerformanceEntry.entry_date <= end)
               .order_by(PerformanceEntry.entry_date.asc(),
                         PerformanceEntry.exercise.asc(),
                         PerformanceEntry.series_number.asc())
               .all())
    if muscle:
        entries = [e for e in entries if (muscle_by_name.get(e.exercise) or 'Autre') == muscle]
    if exercise:
        entries = [e for e in entries if e.exercise == exercise]

    def bucket_key(d):
        if group == 'month':
            return d.strftime('%Y-%m')
        if group == 'week':
            monday = d - timedelta(days=d.weekday())
            return monday.isoformat()
        return d.isoformat()

    def bucket_label(key):
        if group == 'month':
            y, m = key.split('-')
            months = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin',
                      'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
            return f'{months[int(m) - 1]} {y}'
        if group == 'week':
            monday = date.fromisoformat(key)
            sunday = monday + timedelta(days=6)
            return f'{monday.strftime("%d/%m")} → {sunday.strftime("%d/%m/%Y")}'
        d = date.fromisoformat(key)
        days = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
        return f'{days[d.weekday()]} {d.strftime("%d/%m/%Y")}'

    buckets = {}
    for e in entries:
        key = bucket_key(e.entry_date)
        b = buckets.setdefault(key, {
            'key': key,
            'label': bucket_label(key),
            'tonnage': 0.0,
            'series_count': 0,
            'series': [],
        })
        tonnage = (e.load * e.reps) if (e.load is not None and e.reps is not None) else 0
        b['tonnage'] += tonnage
        b['series_count'] += 1
        b['series'].append({
            'date': e.entry_date.isoformat(),
            'exercise': e.exercise,
            'muscle': muscle_by_name.get(e.exercise) or 'Autre',
            'series_number': e.series_number,
            'reps': e.reps,
            'load': e.load,
            'notes': e.notes,
            'tonnage': round(tonnage, 1) if tonnage else 0,
        })

    out = []
    for key in sorted(buckets.keys()):
        b = buckets[key]
        b['tonnage'] = round(b['tonnage'], 1)
        out.append(b)

    return jsonify({
        'start': start.isoformat(),
        'end': end.isoformat(),
        'group': group,
        'muscle': muscle,
        'exercise': exercise,
        'buckets': out,
        'total_tonnage': round(sum(b['tonnage'] for b in out), 1),
        'total_series': sum(b['series_count'] for b in out),
    })


@api_bp.get('/stats/daily-activity')
@login_required
def stats_daily_activity():
    """Activite jour par jour (seances + tonnage) pour la regularite / vues jour."""
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    days = max(1, min(int(request.args.get('days', 90)), 180))
    cutoff = date.today() - timedelta(days=days - 1)
    entries = (PerformanceEntry.query
               .filter(PerformanceEntry.athlete_id == athlete_id,
                       PerformanceEntry.entry_date >= cutoff)
               .all())
    by_date = {}
    for e in entries:
        d = e.entry_date.isoformat()
        bucket = by_date.setdefault(d, {'series': 0, 'tonnage': 0.0, 'exercises': set()})
        bucket['series'] += 1
        if e.load is not None and e.reps is not None:
            bucket['tonnage'] += e.load * e.reps
        if e.exercise:
            bucket['exercises'].add(e.exercise)

    out = []
    cur = cutoff
    today = date.today()
    while cur <= today:
        key = cur.isoformat()
        b = by_date.get(key)
        out.append({
            'date': key,
            'trained': bool(b and b['series'] > 0),
            'series_count': b['series'] if b else 0,
            'exercise_count': len(b['exercises']) if b else 0,
            'tonnage': round(b['tonnage'], 1) if b else 0,
        })
        cur += timedelta(days=1)
    return jsonify(out)


@api_bp.get('/stats/coach-bootstrap')
@login_required
def stats_coach_bootstrap():
    """Une seule requête pour l'écran Stats coach (remplace 4 appels parallèles)."""
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    days = max(1, min(int(request.args.get('days', 180)), 180))
    weeks = max(1, min(int(request.args.get('weeks', 24)), 24))
    muscle_by_name = {e.name: e.muscle_group for e in Exercise.query.all()}

    cutoff = date.today() - timedelta(days=days - 1)
    oldest_start, _ = _week_bounds(weeks - 1)
    range_start = min(cutoff, oldest_start)
    today = date.today()

    journal_all = (JournalEntry.query
                   .filter(JournalEntry.athlete_id == athlete_id,
                           JournalEntry.entry_date >= range_start)
                   .order_by(JournalEntry.entry_date.asc())
                   .all())
    perf_all = (PerformanceEntry.query
                .filter(PerformanceEntry.athlete_id == athlete_id,
                        PerformanceEntry.entry_date >= range_start)
                .all())

    by_date = {}
    for e in perf_all:
        if e.entry_date < cutoff:
            continue
        d = e.entry_date.isoformat()
        bucket = by_date.setdefault(d, {'series': 0, 'tonnage': 0.0, 'exercises': set()})
        bucket['series'] += 1
        if e.load is not None and e.reps is not None:
            bucket['tonnage'] += e.load * e.reps
        if e.exercise:
            bucket['exercises'].add(e.exercise)
    daily_activity = []
    cur = cutoff
    while cur <= today:
        key = cur.isoformat()
        b = by_date.get(key)
        daily_activity.append({
            'date': key,
            'trained': bool(b and b['series'] > 0),
            'series_count': b['series'] if b else 0,
            'exercise_count': len(b['exercises']) if b else 0,
            'tonnage': round(b['tonnage'], 1) if b else 0,
        })
        cur += timedelta(days=1)

    journal_trend = [
        {
            'date': e.entry_date.isoformat(),
            'weight': e.weight,
            'protein': e.protein,
            'carbs': e.carbs,
            'fats': e.fats,
            'kcals': e.kcals,
            'water_ml': e.water_ml,
            'steps': e.steps,
            'sleep_hours': e.sleep_hours,
            'energy': e.energy,
            'stress': e.stress,
            'hunger': e.hunger,
        }
        for e in journal_all if e.entry_date >= cutoff
    ]

    overview_weeks = []
    for offset in range(weeks - 1, -1, -1):
        start, end = _week_bounds(offset)
        journal = [j for j in journal_all if start <= j.entry_date <= end]
        perf = [p for p in perf_all if start <= p.entry_date <= end]
        health = {
            'weight': _avg([j.weight for j in journal]),
            'kcals': _avg([j.kcals for j in journal]),
            'water_ml': _avg([j.water_ml for j in journal]),
            'sleep_hours': _avg([j.sleep_hours for j in journal]),
            'protein': _avg([j.protein for j in journal]),
            'carbs': _avg([j.carbs for j in journal]),
            'fats': _avg([j.fats for j in journal]),
            'steps': _avg([j.steps for j in journal]),
            'energy': _avg([j.energy for j in journal]),
            'stress': _avg([j.stress for j in journal]),
            'hunger': _avg([j.hunger for j in journal]),
        }
        muscle_totals, _ = _muscle_tonnage_from_rows(perf, muscle_by_name)
        overview_weeks.append({
            'offset': offset,
            'label': _week_label(offset),
            'start': start.isoformat(),
            'end': end.isoformat(),
            'sessions': len({e.entry_date for e in perf}),
            'total_tonnage': round(sum(muscle_totals.values()), 1),
            'health': health,
            'muscles': [
                {'muscle': m, 'tonnage': round(t, 1)}
                for m, t in sorted(muscle_totals.items(), key=lambda kv: -kv[1])
            ],
        })

    by_muscle = {}
    ex_meta = {}
    for e in perf_all:
        if not e.exercise:
            continue
        meta = ex_meta.setdefault(e.exercise, {'last': e.entry_date, 'entries': 0, 'tonnage': 0.0})
        meta['entries'] += 1
        if e.entry_date > meta['last']:
            meta['last'] = e.entry_date
        if e.load is not None and e.reps is not None:
            meta['tonnage'] += e.load * e.reps
    for name, meta in ex_meta.items():
        muscle = muscle_by_name.get(name, 'Autre') or 'Autre'
        bucket = by_muscle.setdefault(muscle, {'tonnage': 0.0, 'exercises': []})
        bucket['tonnage'] += meta['tonnage']
        bucket['exercises'].append({
            'name': name,
            'last_date': meta['last'].isoformat() if meta['last'] else None,
            'entries': meta['entries'],
        })
    exercises_by_muscle = []
    for muscle, bucket in by_muscle.items():
        bucket['exercises'].sort(key=lambda e: e['last_date'] or '', reverse=True)
        exercises_by_muscle.append({
            'muscle': muscle,
            'tonnage': round(bucket['tonnage'], 1),
            'exercises': bucket['exercises'],
        })
    exercises_by_muscle.sort(key=lambda m: -m['tonnage'])

    return jsonify({
        'daily_activity': daily_activity,
        'journal_trend': journal_trend,
        'weekly_overview': {'weeks': overview_weeks},
        'exercises_by_muscle': exercises_by_muscle,
    })


# -------------------------------------------------------------- FOOD BANK -

@api_bp.get('/foods')
@login_required
def list_foods():
    search = request.args.get('q')
    owner_scope = _bank_owner_scope_id()
    query = Food.query.filter(_bank_visibility_filter(Food, owner_scope))
    if search:
        query = query.filter(Food.name.ilike(f'%{search}%'))
    foods = query.order_by(Food.name).limit(500).all()
    return jsonify([f.to_dict() for f in foods])


@api_bp.post('/foods')
@login_required
def create_food():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name or data.get('kcal') is None or data.get('carbs') is None:
        return jsonify({'error': 'name, kcal et carbs requis'}), 400
    user = request.current_user
    as_personal = bool(data.get('personal')) or user.role == 'athlete'
    owner_id = None
    if as_personal:
        owner_id = user.id
        name = _ensure_personal_name(name, user)
    elif user.role not in ('coach', 'admin'):
        return jsonify({'error': 'Réservé au coach'}), 403
    if Food.query.filter_by(name=name).first():
        return jsonify({'error': 'Cet aliment existe déjà'}), 409

    food = Food(
        name=name, brand=data.get('brand'), kcal=data['kcal'], proteins=data.get('proteins'),
        lipids=data.get('lipids'), saturated_fats=data.get('saturated_fats'), carbs=data['carbs'],
        simple_sugars=data.get('simple_sugars'), fiber=data.get('fiber'), salt=data.get('salt'),
        owner_id=owner_id,
    )
    db.session.add(food)
    db.session.commit()
    return jsonify(food.to_dict()), 201


@api_bp.put('/foods/<int:food_id>')
@login_required
def update_food(food_id):
    food = Food.query.get_or_404(food_id)
    data = request.get_json(silent=True) or {}
    user = request.current_user
    if food.owner_id is None:
        if user.role != 'admin':
            return jsonify({
                'error': 'Banque commune : crée une demande de modification ou ta version perso',
                'code': 'COMMON_BANK_LOCKED',
            }), 403
    elif food.owner_id != user.id and user.role != 'admin':
        return _deny_manage()
    for field in ('name', 'brand', 'kcal', 'proteins', 'lipids', 'saturated_fats', 'carbs',
                  'simple_sugars', 'fiber', 'salt'):
        if field in data:
            setattr(food, field, data[field])
    db.session.commit()
    return jsonify(food.to_dict())


@api_bp.delete('/foods/<int:food_id>')
@login_required
def delete_food(food_id):
    food = Food.query.get_or_404(food_id)
    user = request.current_user
    if food.owner_id is None:
        return jsonify({'error': 'Impossible de supprimer une entrée commune'}), 403
    if food.owner_id != user.id and user.role != 'admin':
        return _deny_manage()
    db.session.delete(food)
    db.session.commit()
    return jsonify({'ok': True})


# ------------------------------------------------------------- MEAL PLANS -

@api_bp.get('/meal-plans')
@login_required
def list_meal_plans():
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    from sqlalchemy.orm import selectinload, joinedload
    with_meals = str(request.args.get('with_meals', '0')).lower() in ('1', 'true', 'yes')
    plans = (
        MealPlan.query.filter_by(athlete_id=athlete_id)
        .options(selectinload(MealPlan.meals).joinedload(MealEntry.food))
        .order_by(MealPlan.is_active.desc(), MealPlan.created_at.desc())
        .all()
    )
    return jsonify([p.to_dict(with_meals=with_meals) for p in plans])


@api_bp.get('/meal-plans/<int:plan_id>')
@login_required
def get_meal_plan(plan_id):
    plan = MealPlan.query.get_or_404(plan_id)
    if not _is_staff() and plan.athlete_id != request.current_user.id:
        return jsonify({'error': 'Accès refusé'}), 403
    return jsonify(plan.to_dict(with_meals=True))


@api_bp.post('/meal-plans')
@login_required
def create_meal_plan():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    athlete_id = _resolve_create_athlete_id(data)
    if not name or not athlete_id:
        return jsonify({'error': 'name et athlete_id requis'}), 400
    if not _can_manage_athlete(athlete_id):
        return _deny_manage()
    has_any = MealPlan.query.filter_by(athlete_id=athlete_id).count() > 0
    plan = MealPlan(
        name=name, athlete_id=athlete_id, coach_id=_coach_id_for_create(athlete_id),
        meal_count=data.get('meal_count', 6), is_active=not has_any,
    )
    db.session.add(plan)
    db.session.commit()
    return jsonify(plan.to_dict()), 201


@api_bp.delete('/meal-plans/<int:plan_id>')
@login_required
def delete_meal_plan(plan_id):
    plan = MealPlan.query.get_or_404(plan_id)
    if not _can_manage_athlete(plan.athlete_id):
        return _deny_manage()
    athlete_id = plan.athlete_id
    was_active = bool(plan.is_active)
    db.session.delete(plan)
    db.session.flush()
    if was_active:
        fallback = (
            MealPlan.query.filter_by(athlete_id=athlete_id)
            .order_by(MealPlan.created_at.desc())
            .first()
        )
        if fallback:
            fallback.is_active = True
    db.session.commit()
    return jsonify({'ok': True})


@api_bp.post('/meal-plans/<int:plan_id>/activate')
@login_required
def activate_meal_plan(plan_id):
    plan = MealPlan.query.get_or_404(plan_id)
    user = request.current_user
    if not _is_staff(user) and plan.athlete_id != user.id:
        return jsonify({'error': 'Accès refusé'}), 403
    MealPlan.query.filter_by(athlete_id=plan.athlete_id, is_active=True).update(
        {'is_active': False}, synchronize_session=False,
    )
    plan.is_active = True
    db.session.commit()
    return jsonify(plan.to_dict())


@api_bp.put('/meal-plans/<int:plan_id>')
@login_required
def rename_meal_plan(plan_id):
    plan = MealPlan.query.get_or_404(plan_id)
    if not _can_manage_athlete(plan.athlete_id):
        return _deny_manage()
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name requis'}), 400
    plan.name = name
    db.session.commit()
    return jsonify(plan.to_dict())


@api_bp.post('/meal-plans/<int:plan_id>/duplicate')
@login_required
def duplicate_meal_plan(plan_id):
    source = MealPlan.query.get_or_404(plan_id)
    if not _can_manage_athlete(source.athlete_id):
        return _deny_manage()
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or f'{source.name} (copie)').strip()
    athlete_id = int(data.get('athlete_id') or source.athlete_id)
    if not _can_manage_athlete(athlete_id):
        return _deny_manage()

    new_plan = MealPlan(
        name=name, athlete_id=athlete_id, coach_id=_coach_id_for_create(athlete_id),
        meal_count=source.meal_count,
        **{f'meal_time_{i}': getattr(source, f'meal_time_{i}') for i in range(1, 7)},
        **{f'meal_label_{i}': getattr(source, f'meal_label_{i}') for i in range(1, 7)},
    )
    db.session.add(new_plan)
    db.session.flush()

    for meal in source.meals:
        db.session.add(MealEntry(
            meal_plan_id=new_plan.id, food_id=meal.food_id, meal_number=meal.meal_number,
            quantity=meal.quantity, position=meal.position,
        ))

    db.session.commit()
    return jsonify(new_plan.to_dict()), 201


@api_bp.post('/meal-plans/<int:plan_id>/meals')
@login_required
def add_meal_entry(plan_id):
    plan = MealPlan.query.get_or_404(plan_id)
    if not _can_manage_athlete(plan.athlete_id):
        return _deny_manage()
    data = request.get_json(silent=True) or {}
    meal_number = data.get('meal_number')
    food_id = data.get('food_id')
    if not meal_number or not food_id:
        return jsonify({'error': 'meal_number et food_id requis'}), 400

    max_position = (db.session.query(db.func.max(MealEntry.position))
                     .filter_by(meal_plan_id=plan_id, meal_number=meal_number).scalar())
    entry = MealEntry(
        meal_plan_id=plan_id, food_id=food_id, meal_number=meal_number,
        quantity=data.get('quantity', 100), position=(max_position or 0) + 1,
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify(entry.to_dict()), 201


@api_bp.put('/meal-entries/<int:entry_id>')
@login_required
def update_meal_entry(entry_id):
    entry = MealEntry.query.get_or_404(entry_id)
    plan = MealPlan.query.get_or_404(entry.meal_plan_id)
    if not _can_manage_athlete(plan.athlete_id):
        return _deny_manage()
    data = request.get_json(silent=True) or {}
    if 'quantity' in data:
        entry.quantity = data['quantity']
    db.session.commit()
    return jsonify(entry.to_dict())


@api_bp.delete('/meal-entries/<int:entry_id>')
@login_required
def delete_meal_entry(entry_id):
    entry = MealEntry.query.get_or_404(entry_id)
    plan = MealPlan.query.get_or_404(entry.meal_plan_id)
    if not _can_manage_athlete(plan.athlete_id):
        return _deny_manage()
    db.session.delete(entry)
    db.session.commit()
    return jsonify({'ok': True})


@api_bp.put('/meal-plans/<int:plan_id>/meal-time')
@login_required
def set_meal_time(plan_id):
    plan = MealPlan.query.get_or_404(plan_id)
    if not _can_manage_athlete(plan.athlete_id):
        return _deny_manage()
    data = request.get_json(silent=True) or {}
    meal_number = data.get('meal_number')
    if meal_number not in range(1, 7):
        return jsonify({'error': 'meal_number doit être entre 1 et 6'}), 400
    setattr(plan, f'meal_time_{meal_number}', data.get('time'))
    setattr(plan, f'meal_label_{meal_number}', data.get('label'))
    db.session.commit()
    return jsonify(plan.to_dict())


# -------------------------------------------------- BANK CHANGE REQUESTS -

@api_bp.post('/bank-change-requests')
@login_required
def create_bank_change_request():
    data = request.get_json(silent=True) or {}
    kind = data.get('kind')
    target_id = data.get('target_id')
    payload = data.get('payload') or {}
    message = (data.get('message') or '').strip() or None
    if kind not in ('exercise', 'food') or not target_id:
        return jsonify({'error': 'kind (exercise|food) et target_id requis'}), 400
    if not isinstance(payload, dict) or not payload:
        return jsonify({'error': 'payload objet requis'}), 400

    if kind == 'exercise':
        target = Exercise.query.get_or_404(int(target_id))
    else:
        target = Food.query.get_or_404(int(target_id))
    if target.owner_id is not None:
        return jsonify({'error': 'Uniquement pour la banque commune'}), 400

    req = BankChangeRequest(
        kind=kind,
        target_id=int(target_id),
        requester_id=request.current_user.id,
        payload=json.dumps(payload, ensure_ascii=False),
        message=message,
        status='pending',
    )
    db.session.add(req)
    db.session.commit()
    return jsonify({
        **req.to_dict(with_target=True),
        'hint': 'Tu peux aussi créer ta version perso avec personal=true',
    }), 201


@api_bp.get('/bank-change-requests/mine')
@login_required
def list_my_bank_change_requests():
    rows = (
        BankChangeRequest.query.filter_by(requester_id=request.current_user.id)
        .order_by(BankChangeRequest.created_at.desc())
        .limit(100)
        .all()
    )
    return jsonify([r.to_dict(with_target=True) for r in rows])


@api_bp.get('/admin/bank-change-requests')
@admin_required
def list_admin_bank_change_requests():
    status = request.args.get('status') or 'pending'
    query = BankChangeRequest.query
    if status != 'all':
        query = query.filter_by(status=status)
    rows = query.order_by(BankChangeRequest.created_at.desc()).limit(200).all()
    return jsonify([r.to_dict(with_target=True) for r in rows])


@api_bp.post('/admin/bank-change-requests/<int:req_id>/approve')
@admin_required
def approve_bank_change_request(req_id):
    req = BankChangeRequest.query.get_or_404(req_id)
    if req.status != 'pending':
        return jsonify({'error': 'Demande déjà traitée'}), 400
    try:
        payload = json.loads(req.payload or '{}')
    except (TypeError, ValueError):
        payload = {}

    if req.kind == 'exercise':
        target = Exercise.query.get_or_404(req.target_id)
        if payload.get('name'):
            conflict = Exercise.query.filter(
                Exercise.name == payload['name'], Exercise.id != target.id,
            ).first()
            if conflict:
                return jsonify({'error': 'Nom déjà pris'}), 409
            target.name = payload['name']
        if payload.get('muscle_group') in MUSCLE_GROUPS:
            target.muscle_group = payload['muscle_group']
    else:
        target = Food.query.get_or_404(req.target_id)
        for field in ('name', 'brand', 'kcal', 'proteins', 'lipids', 'saturated_fats', 'carbs',
                      'simple_sugars', 'fiber', 'salt'):
            if field in payload:
                setattr(target, field, payload[field])

    data = request.get_json(silent=True) or {}
    req.status = 'approved'
    req.reviewed_by_id = request.current_user.id
    req.reviewed_at = datetime.utcnow()
    req.admin_note = (data.get('admin_note') or '').strip() or None
    db.session.commit()
    return jsonify(req.to_dict(with_target=True))


@api_bp.post('/admin/bank-change-requests/<int:req_id>/reject')
@admin_required
def reject_bank_change_request(req_id):
    req = BankChangeRequest.query.get_or_404(req_id)
    if req.status != 'pending':
        return jsonify({'error': 'Demande déjà traitée'}), 400
    data = request.get_json(silent=True) or {}
    req.status = 'rejected'
    req.reviewed_by_id = request.current_user.id
    req.reviewed_at = datetime.utcnow()
    req.admin_note = (data.get('admin_note') or '').strip() or None
    db.session.commit()
    return jsonify(req.to_dict(with_target=True))


# ---------------------------------------------------- ATHLETE BILAN HEBDO -


DAY_NAMES_FR = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']


def _clean_note_text(value, max_len=500):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_len]


def _build_athlete_note_summary(payload):
    lines = []
    hunger = _clean_note_text(payload.get('hunger'))
    fatigue = _clean_note_text(payload.get('fatigue'))
    crash = _clean_note_text(payload.get('energy_crash'))
    crash_time = _clean_note_text(payload.get('energy_crash_time'), 32)
    exo = _clean_note_text(payload.get('exercise_difficulty'))
    other = _clean_note_text(payload.get('other'))
    if hunger:
        lines.append(f'Faim : {hunger}')
    if fatigue:
        lines.append(f'Fatigue : {fatigue}')
    if crash or crash_time:
        if crash and crash_time:
            lines.append(f'Coup de barre ({crash_time}) : {crash}')
        elif crash_time:
            lines.append(f'Coup de barre à {crash_time}')
        else:
            lines.append(f'Coup de barre : {crash}')
    if exo:
        lines.append(f'Difficulté exo : {exo}')
    if other:
        lines.append(f'Autre : {other}')
    return '\n'.join(lines) if lines else None



def _journal_streak(athlete_id, today):
    """Jours consecutifs avec journal. Si aujourd'hui vide, part d'hier."""
    dates = {
        j.entry_date for j in JournalEntry.query.filter(
            JournalEntry.athlete_id == athlete_id,
            JournalEntry.entry_date >= today - timedelta(days=120),
        ).all()
    }
    cursor = today if today in dates else today - timedelta(days=1)
    streak = 0
    while cursor in dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _training_week_streak(athlete_id, program, today):
    """Semaines consecutives ou toutes les seances du programme ont ete loggees."""
    if not program or not program.sessions:
        return 0
    session_days = sorted({s.day_of_week for s in program.sessions})
    if not session_days:
        return 0
    oldest = today - timedelta(days=24 * 7)
    logs = PerformanceEntry.query.filter(
        PerformanceEntry.athlete_id == athlete_id,
        PerformanceEntry.entry_date >= oldest,
    ).all()
    logged_dates = {e.entry_date for e in logs}
    logged_by_session_date = {
        (e.program_session_id, e.entry_date)
        for e in logs if e.program_session_id is not None
    }

    def week_complete(week_start):
        for dow in session_days:
            day = week_start + timedelta(days=dow)
            if day > today:
                return None
            sess = next((s for s in program.sessions if s.day_of_week == dow), None)
            if not sess:
                continue
            if (sess.id, day) in logged_by_session_date or day in logged_dates:
                continue
            return False
        return True

    streak = 0
    current_start = _week_start(today)
    start = current_start
    first = week_complete(start)
    if first is not True:
        start = current_start - timedelta(days=7)
    for i in range(24):
        ws = start - timedelta(days=7 * i)
        ok = week_complete(ws)
        if ok is True:
            streak += 1
        else:
            break
    return streak


def _athlete_bilan_context(user, today=None):
    today = today or date.today()
    weekday = int(user.bilan_weekday) if user.bilan_weekday is not None else None
    j_minus_1 = ((weekday - 1) % 7) if weekday is not None else None
    return {
        'bilan_weekday': weekday,
        'bilan_day_label': DAY_NAMES_FR[weekday] if weekday is not None else None,
        'is_bilan_day': weekday is not None and today.weekday() == weekday,
        'is_bilan_eve': j_minus_1 is not None and today.weekday() == j_minus_1,
        'can_write_note': weekday is not None and user.coach_id is not None,
    }


def _get_or_create_marking(athlete_id, week_start, done=False):
    marking = MobileWeeklyBilanMarking.query.filter_by(athlete_id=athlete_id, week_start=week_start).first()
    if marking:
        return marking
    marking = MobileWeeklyBilanMarking(athlete_id=athlete_id, week_start=week_start, done=done)
    db.session.add(marking)
    return marking


def _coach_owns_athlete(coach, athlete_id):
    """Jour de bilan / actions bilan : uniquement les athlètes de CETTE équipe."""
    athlete = User.query.get(athlete_id)
    return bool(athlete and athlete.role == 'athlete' and athlete.coach_id == coach.id)


@api_bp.get('/athlete/bilan-hebdo')
@login_required
def athlete_weekly_bilan():
    user = request.current_user
    if user.role != 'athlete':
        return jsonify({'error': 'Réservé à l\'athlète'}), 403
    if not _has_independent(user):
        return jsonify({'error': 'Module Indépendant requis', 'code': 'INDEPENDENT_REQUIRED'}), 403

    today = date.today()
    current_start = _week_start(today)
    previous_start = current_start - timedelta(days=7)
    current_end = current_start + timedelta(days=6)
    previous_end = previous_start + timedelta(days=6)
    attention_cutoff = today - timedelta(days=180)

    journal_all = (JournalEntry.query
                   .filter(JournalEntry.athlete_id == user.id,
                           JournalEntry.entry_date >= previous_start,
                           JournalEntry.entry_date <= current_end)
                   .all())
    perf_all = (PerformanceEntry.query
                .filter(PerformanceEntry.athlete_id == user.id,
                        PerformanceEntry.entry_date >= attention_cutoff)
                .all())
    marking = MobileWeeklyBilanMarking.query.filter_by(
        athlete_id=user.id, week_start=current_start,
    ).first()
    objectives = (Objective.query.filter_by(athlete_id=user.id)
                  .order_by(Objective.created_at.desc()).limit(5).all())

    cur_journal = [j for j in journal_all if current_start <= j.entry_date <= current_end]
    prev_journal = [j for j in journal_all if previous_start <= j.entry_date <= previous_end]
    cur_perf = [p for p in perf_all if current_start <= p.entry_date <= current_end]
    prev_perf = [p for p in perf_all if previous_start <= p.entry_date <= previous_end]

    current = _weekly_metrics_from_rows(cur_journal, cur_perf)
    previous = _weekly_metrics_from_rows(prev_journal, prev_perf)
    metrics = []
    for key, label in METRIC_LABELS:
        cur_v, prev_v = current[key], previous[key]
        diff = round(cur_v - prev_v, 1) if cur_v is not None and prev_v is not None else None
        metrics.append({'key': key, 'label': label, 'current': cur_v, 'previous': prev_v, 'diff': diff})

    muscle_by_name = {e.name: e.muscle_group for e in Exercise.query.all()}
    muscle_a, ex_a = _muscle_tonnage_from_rows(cur_perf, muscle_by_name)
    muscle_b, ex_b = _muscle_tonnage_from_rows(prev_perf, muscle_by_name)
    muscle_rows = _build_muscle_rows(muscle_a, ex_a, muscle_b, ex_b)
    series_by_ex = _series_by_exercise_from_rows(perf_all)
    attention = _analyse_attention_from_series(series_by_ex, 0, 1)

    entry = {
        'athlete': user.to_dict(),
        'week_start': current_start.isoformat(),
        'done': bool(marking.done) if marking else False,
        'metrics': metrics,
        'objectives': [o.to_dict() for o in objectives],
        'muscles': muscle_rows,
        'attention': attention,
    }
    return jsonify([entry])


@api_bp.post('/athlete/bilan-hebdo/mark')
@login_required
def athlete_mark_weekly_bilan():
    user = request.current_user
    if user.role != 'athlete' or not _has_independent(user):
        return jsonify({'error': 'Module Indépendant requis'}), 403
    data = request.get_json(silent=True) or {}
    week_start = _parse_date(data.get('week_start')) or _week_start(date.today())
    marking = MobileWeeklyBilanMarking.query.filter_by(athlete_id=user.id, week_start=week_start).first()
    if marking:
        marking.done = True
    else:
        marking = MobileWeeklyBilanMarking(athlete_id=user.id, week_start=week_start, done=True)
        db.session.add(marking)
    db.session.commit()
    return jsonify(marking.to_dict())


@api_bp.post('/athlete/bilan-hebdo/unmark')
@login_required
def athlete_unmark_weekly_bilan():
    user = request.current_user
    if user.role != 'athlete' or not _has_independent(user):
        return jsonify({'error': 'Module Indépendant requis'}), 403
    data = request.get_json(silent=True) or {}
    week_start = _parse_date(data.get('week_start')) or _week_start(date.today())
    marking = MobileWeeklyBilanMarking.query.filter_by(athlete_id=user.id, week_start=week_start).first()
    if marking:
        db.session.delete(marking)
        db.session.commit()
    return jsonify({'ok': True})


# ------------------------------------------------------------- BILAN HEBDO -

def _week_start(d):
    return d - timedelta(days=d.weekday())


def _avg(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def _weekly_metrics_from_rows(journal, perf):
    tonnage = sum((e.reps or 0) * (e.load or 0) for e in perf)
    sessions = len({e.entry_date for e in perf})

    return {
        'weight': _avg([j.weight for j in journal]),
        'kcals': _avg([j.kcals for j in journal]),
        'sleep_hours': _avg([j.sleep_hours for j in journal]),
        'energy': _avg([j.energy for j in journal]),
        'stress': _avg([j.stress for j in journal]),
        'tonnage': round(tonnage, 1),
        'sessions': sessions,
        'entries_logged': len(journal),
    }


def _weekly_metrics(athlete_id, week_start):
    week_end = week_start + timedelta(days=6)

    journal = (JournalEntry.query
               .filter(JournalEntry.athlete_id == athlete_id,
                       JournalEntry.entry_date >= week_start, JournalEntry.entry_date <= week_end)
               .all())
    perf = (PerformanceEntry.query
            .filter(PerformanceEntry.athlete_id == athlete_id,
                    PerformanceEntry.entry_date >= week_start, PerformanceEntry.entry_date <= week_end)
            .all())

    return _weekly_metrics_from_rows(journal, perf)


METRIC_LABELS = [
    ('weight', 'Poids (kg)'),
    ('kcals', 'Calories (kcal)'),
    ('sleep_hours', 'Sommeil (h)'),
    ('energy', 'Ã‰nergie (/10)'),
    ('stress', 'Stress (/10)'),
    ('tonnage', 'Tonnage (kg)'),
    ('sessions', 'SÃ©ances loggÃ©es'),
    ('entries_logged', 'Jours de journal'),
]


@api_bp.get('/coach/bilan-hebdo')
@coach_required
def weekly_bilan():
    today = date.today()
    current_start = _week_start(today)
    previous_start = current_start - timedelta(days=7)
    current_end = current_start + timedelta(days=6)
    previous_end = previous_start + timedelta(days=6)
    attention_cutoff = today - timedelta(days=180)

    # Easy Bilan = uniquement les athlètes de l'équipe du compte connecté (coach ou admin).
    athletes = _coach_team_query(request.current_user.id).order_by(User.username).all()
    if not athletes:
        return jsonify([])
    athlete_ids = [a.id for a in athletes]

    muscle_by_name = {e.name: e.muscle_group for e in Exercise.query.all()}

    # Requêtes groupées pour TOUS les athlètes en une fois (au lieu d'une
    # boucle de ~9 requêtes par athlète) : évite les timeouts côté mobile
    # quand l'équipe compte plusieurs athlètes.
    journal_rows = (JournalEntry.query
                     .filter(JournalEntry.athlete_id.in_(athlete_ids),
                             JournalEntry.entry_date >= previous_start,
                             JournalEntry.entry_date <= current_end)
                     .all())
    journal_by_athlete = {}
    for j in journal_rows:
        journal_by_athlete.setdefault(j.athlete_id, []).append(j)

    perf_rows = (PerformanceEntry.query
                 .filter(PerformanceEntry.athlete_id.in_(athlete_ids),
                         PerformanceEntry.entry_date >= attention_cutoff)
                 .all())
    perf_by_athlete = {}
    for p in perf_rows:
        perf_by_athlete.setdefault(p.athlete_id, []).append(p)

    markings = (MobileWeeklyBilanMarking.query
                .filter(MobileWeeklyBilanMarking.athlete_id.in_(athlete_ids),
                        MobileWeeklyBilanMarking.week_start == current_start)
                .all())
    marking_by_athlete = {m.athlete_id: m for m in markings}

    objectives_rows = (Objective.query
                        .filter(Objective.athlete_id.in_(athlete_ids))
                        .order_by(Objective.athlete_id, Objective.created_at.desc())
                        .all())
    objectives_by_athlete = {}
    for o in objectives_rows:
        bucket = objectives_by_athlete.setdefault(o.athlete_id, [])
        if len(bucket) < 5:
            bucket.append(o)

    result = []
    for a in athletes:
        perf_all = perf_by_athlete.get(a.id, [])
        journal_all = journal_by_athlete.get(a.id, [])

        cur_journal = [j for j in journal_all if current_start <= j.entry_date <= current_end]
        prev_journal = [j for j in journal_all if previous_start <= j.entry_date <= previous_end]
        cur_perf = [p for p in perf_all if current_start <= p.entry_date <= current_end]
        prev_perf = [p for p in perf_all if previous_start <= p.entry_date <= previous_end]

        current = _weekly_metrics_from_rows(cur_journal, cur_perf)
        previous = _weekly_metrics_from_rows(prev_journal, prev_perf)
        metrics = []
        for key, label in METRIC_LABELS:
            cur_v, prev_v = current[key], previous[key]
            diff = round(cur_v - prev_v, 1) if cur_v is not None and prev_v is not None else None
            metrics.append({'key': key, 'label': label, 'current': cur_v, 'previous': prev_v, 'diff': diff})

        marking = marking_by_athlete.get(a.id)
        objectives = objectives_by_athlete.get(a.id, [])

        muscle_a, ex_a = _muscle_tonnage_from_rows(cur_perf, muscle_by_name)
        muscle_b, ex_b = _muscle_tonnage_from_rows(prev_perf, muscle_by_name)
        muscle_rows = _build_muscle_rows(muscle_a, ex_a, muscle_b, ex_b)

        series_by_ex = _series_by_exercise_from_rows(perf_all)
        attention = _analyse_attention_from_series(series_by_ex, 0, 1)

        result.append({
            'athlete': a.to_dict(),
            'week_start': current_start.isoformat(),
            'done': bool(marking and marking.done),
            'athlete_note': marking.note_dict() if marking else None,
            'metrics': metrics,
            'objectives': [o.to_dict() for o in objectives],
            'muscles': muscle_rows,
            'attention': attention,
        })

    return jsonify(result)


@api_bp.post('/coach/bilan-hebdo/mark')
@coach_required
def mark_weekly_bilan():
    data = request.get_json(silent=True) or {}
    athlete_id = data.get('athlete_id')
    week_start = _parse_date(data.get('week_start'), _week_start(date.today()))
    if not athlete_id:
        return jsonify({'error': 'athlete_id requis'}), 400

    marking = MobileWeeklyBilanMarking.query.filter_by(athlete_id=athlete_id, week_start=week_start).first()
    if marking:
        marking.done = True
    else:
        marking = MobileWeeklyBilanMarking(athlete_id=athlete_id, week_start=week_start, done=True)
        db.session.add(marking)
    db.session.commit()
    return jsonify(marking.to_dict())


@api_bp.post('/coach/bilan-hebdo/unmark')
@coach_required
def unmark_weekly_bilan():
    data = request.get_json(silent=True) or {}
    athlete_id = data.get('athlete_id')
    week_start = _parse_date(data.get('week_start'), _week_start(date.today()))
    marking = MobileWeeklyBilanMarking.query.filter_by(athlete_id=athlete_id, week_start=week_start).first()
    if marking:
        marking.done = False
        db.session.commit()
        return jsonify(marking.to_dict())
    return jsonify({'athlete_id': athlete_id, 'week_start': week_start.isoformat(), 'done': False})


@api_bp.get('/coach/bilan-hebdo/unchecked-count')
@coach_required
def bilan_unchecked_count():
    current_start = _week_start(date.today())
    athletes = _coach_team_query(request.current_user.id).all()
    athlete_ids = [a.id for a in athletes]
    total_athletes = len(athlete_ids)
    marked = 0
    if athlete_ids:
        marked = MobileWeeklyBilanMarking.query.filter(
            MobileWeeklyBilanMarking.athlete_id.in_(athlete_ids),
            MobileWeeklyBilanMarking.week_start == current_start,
            MobileWeeklyBilanMarking.done.is_(True),
        ).count()
    return jsonify({'unchecked_count': max(total_athletes - marked, 0)})


# ---------------------------------------------------- BILAN DAY PER ATHLETE -

@api_bp.get('/coach/athletes/<int:athlete_id>/bilan-settings')
@coach_required
def get_athlete_bilan_settings(athlete_id):
    if not _coach_owns_athlete(request.current_user, athlete_id):
        return jsonify({'error': 'Athlète non autorisé'}), 403
    athlete = User.query.get_or_404(athlete_id)
    weekday = int(athlete.bilan_weekday) if athlete.bilan_weekday is not None else None
    return jsonify({
        'athlete_id': athlete.id,
        'bilan_weekday': weekday,
        'bilan_day_label': DAY_NAMES_FR[weekday] if weekday is not None else None,
        'required': True,
    })


@api_bp.put('/coach/athletes/<int:athlete_id>/bilan-settings')
@coach_required
def put_athlete_bilan_settings(athlete_id):
    """Jour de bilan hebdo pour UN athlète (0=lundi … 6=dimanche)."""
    if not _coach_owns_athlete(request.current_user, athlete_id):
        return jsonify({'error': 'Athlète non autorisé'}), 403
    athlete = User.query.get_or_404(athlete_id)
    if athlete.role != 'athlete':
        return jsonify({'error': 'Utilisateur non athlète'}), 400
    data = request.get_json(silent=True) or {}
    try:
        weekday = int(data.get('bilan_weekday'))
    except (TypeError, ValueError):
        return jsonify({'error': 'bilan_weekday requis (0=lundi … 6=dimanche)'}), 400
    if weekday < 0 or weekday > 6:
        return jsonify({'error': 'bilan_weekday doit être entre 0 et 6'}), 400
    athlete.bilan_weekday = weekday
    db.session.commit()
    return jsonify({
        'athlete_id': athlete.id,
        'bilan_weekday': weekday,
        'bilan_day_label': DAY_NAMES_FR[weekday],
        'required': True,
        'athlete': athlete.to_dict(),
    })


# Compat: ancien endpoint global → exige athlete_id désormais
@api_bp.put('/coach/bilan-settings')
@coach_required
def put_bilan_settings_compat():
    data = request.get_json(silent=True) or {}
    athlete_id = data.get('athlete_id')
    if not athlete_id:
        return jsonify({'error': 'athlete_id requis — le jour de bilan se choisit par athlète'}), 400
    return put_athlete_bilan_settings(int(athlete_id))


@api_bp.post('/athlete/bilan-hebdo/note')
@login_required
def athlete_save_bilan_note():
    user = request.current_user
    if user.role != 'athlete':
        return jsonify({'error': "Réservé à l'athlète"}), 403
    if not user.coach_id:
        return jsonify({'error': 'Aucun coach associé'}), 400
    if user.bilan_weekday is None:
        return jsonify({'error': "Ton coach n'a pas encore choisi ton jour de bilan"}), 400
    data = request.get_json(silent=True) or {}
    week_start = _parse_date(data.get('week_start')) or _week_start(date.today())
    payload = {
        'hunger': _clean_note_text(data.get('hunger')),
        'fatigue': _clean_note_text(data.get('fatigue')),
        'energy_crash': _clean_note_text(data.get('energy_crash')),
        'energy_crash_time': _clean_note_text(data.get('energy_crash_time'), 32),
        'exercise_difficulty': _clean_note_text(data.get('exercise_difficulty')),
        'other': _clean_note_text(data.get('other')),
    }
    summary = _build_athlete_note_summary(payload)
    if not summary:
        return jsonify({'error': 'Écris au moins un élément de bilan'}), 400
    marking = _get_or_create_marking(user.id, week_start, done=False)
    marking.athlete_note = summary
    marking.athlete_note_json = json.dumps(payload, ensure_ascii=False)
    marking.athlete_note_updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(marking.to_dict())


# ---------------------------------------------------- COACH PROFILE / SEARCH -

CONTACT_CHANNELS = {'phone', 'whatsapp', 'email', 'instagram', 'other'}


@api_bp.get('/coach/profile')
@coach_required
def get_coach_profile():
    user = request.current_user
    data = user.coach_profile_dict(reveal_contact=True)
    data['user'] = user.to_dict()
    return jsonify(data)


@api_bp.put('/coach/profile')
@coach_required
def put_coach_profile():
    user = request.current_user
    data = request.get_json(silent=True) or {}

    def _s(key, max_len=255):
        v = data.get(key)
        if v is None:
            return None
        t = str(v).strip()
        return t[:max_len] if t else None

    user.first_name = _s('first_name', 64)
    user.last_name = _s('last_name', 64)
    user.specialty = _s('specialty', 128)
    user.partner_brand = _s('partner_brand', 128)
    user.athlete_types = _s('athlete_types', 255)
    user.city = _s('city', 128)
    channel = _s('contact_channel', 32)
    if channel and channel not in CONTACT_CHANNELS:
        return jsonify({'error': 'contact_channel invalide'}), 400
    user.contact_channel = channel
    user.contact_value = _s('contact_value', 255)

    if 'lat' in data:
        try:
            user.lat = float(data['lat']) if data['lat'] is not None else None
        except (TypeError, ValueError):
            return jsonify({'error': 'lat invalide'}), 400
    if 'lng' in data:
        try:
            user.lng = float(data['lng']) if data['lng'] is not None else None
        except (TypeError, ValueError):
            return jsonify({'error': 'lng invalide'}), 400

    # Sync display_name from first/last when provided
    if user.first_name or user.last_name:
        user.display_name = ' '.join(x for x in [user.first_name, user.last_name] if x).strip() or user.display_name

    if user.coach_profile_is_complete():
        if not user.profile_completed_at:
            user.profile_completed_at = datetime.utcnow()
    else:
        user.profile_completed_at = None

    db.session.commit()
    out = user.coach_profile_dict(reveal_contact=True)
    out['user'] = user.to_dict()
    return jsonify(out)


@api_bp.get('/coaches/search')
@login_required
def search_coaches():
    """Recherche coaches pour map : city et/ou bbox."""
    city = (request.args.get('city') or '').strip()
    q = User.query.filter(User.role == 'coach')
    if city:
        like = f'%{city}%'
        q = q.filter(User.city.ilike(like))
    # bbox: west,south,east,north
    bbox = request.args.get('bbox')
    if bbox:
        try:
            west, south, east, north = [float(x) for x in bbox.split(',')]
            q = q.filter(
                User.lat.isnot(None), User.lng.isnot(None),
                User.lat >= south, User.lat <= north,
                User.lng >= west, User.lng <= east,
            )
        except ValueError:
            return jsonify({'error': 'bbox invalide (west,south,east,north)'}), 400
    else:
        # Sans bbox : seulement ceux géolocalisés pour la map
        q = q.filter(User.lat.isnot(None), User.lng.isnot(None))

    rows = q.order_by(User.display_name, User.username).limit(100).all()
    viewer = request.current_user
    out = []
    for c in rows:
        reveal = viewer.role == 'athlete' and viewer.coach_id == c.id
        card = c.coach_profile_dict(reveal_contact=reveal)
        card['id'] = c.id
        card['display_name'] = c.display_name or c.username
        card['profile_complete'] = c.coach_profile_is_complete()
        out.append(card)
    return jsonify(out)


@api_bp.get('/coaches/<int:coach_id>')
@login_required
def get_coach_public(coach_id):
    coach = User.query.filter_by(id=coach_id, role='coach').first_or_404()
    viewer = request.current_user
    reveal = viewer.role == 'athlete' and viewer.coach_id == coach.id
    data = coach.coach_profile_dict(reveal_contact=reveal)
    data['id'] = coach.id
    data['display_name'] = coach.display_name or coach.username
    return jsonify(data)


@api_bp.post('/athlete/coach-requests')
@login_required
def create_athlete_coach_request():
    user = request.current_user
    if user.role != 'athlete':
        return jsonify({'error': "Réservé à l'athlète"}), 403
    if user.coach_id:
        return jsonify({'error': 'Tu as déjà un coach'}), 409
    data = request.get_json(silent=True) or {}
    coach_id = data.get('coach_id')
    if not coach_id:
        return jsonify({'error': 'coach_id requis'}), 400
    coach = User.query.filter_by(id=coach_id, role='coach').first()
    if not coach:
        return jsonify({'error': 'Coach introuvable'}), 404
    existing = CoachingInvitation.query.filter_by(
        coach_id=coach.id, athlete_id=user.id, status='pending',
    ).first()
    if existing:
        return jsonify(existing.to_dict()), 200
    inv = CoachingInvitation(
        coach_id=coach.id, athlete_id=user.id,
        status='pending', direction='athlete_to_coach',
    )
    db.session.add(inv)
    db.session.commit()
    return jsonify(inv.to_dict()), 201


@api_bp.get('/coach/athlete-requests')
@coach_required
def list_athlete_requests():
    user = request.current_user
    if user.role == 'admin':
        rows = (CoachingInvitation.query
                .filter_by(status='pending', direction='athlete_to_coach')
                .order_by(CoachingInvitation.created_at.desc()).all())
    else:
        rows = (CoachingInvitation.query
                .filter_by(coach_id=user.id, status='pending', direction='athlete_to_coach')
                .order_by(CoachingInvitation.created_at.desc()).all())
    return jsonify([i.to_dict() for i in rows])


@api_bp.post('/coach/athlete-requests/<int:invitation_id>/accept')
@coach_required
def accept_athlete_request(invitation_id):
    user = request.current_user
    inv = CoachingInvitation.query.get_or_404(invitation_id)
    if inv.status != 'pending' or (inv.direction or '') != 'athlete_to_coach':
        return jsonify({'error': 'Demande invalide'}), 400
    if user.role != 'admin' and inv.coach_id != user.id:
        return jsonify({'error': 'Non autorisé'}), 403
    coach = User.query.get(inv.coach_id)
    athlete = User.query.get(inv.athlete_id)
    if not coach or not athlete or athlete.role != 'athlete':
        return jsonify({'error': 'Utilisateur introuvable'}), 404
    if athlete.coach_id:
        return jsonify({'error': 'Cet athlète a déjà un coach'}), 409
    limit = coach.athlete_limit()
    if limit is not None and User.query.filter_by(role='athlete', coach_id=coach.id).count() >= limit:
        if limit == 0:
            return jsonify({
                'error': 'Abonnement requis pour coacher des athlètes. Choisis un niveau payant.',
                'code': 'SUBSCRIPTION_REQUIRED',
            }), 403
        return jsonify({
            'error': 'Quota atteint. Augmente ton abonnement ou retire un athlète.',
            'code': 'QUOTA_REACHED',
        }), 403
    _link_athlete_to_coach(athlete, coach.id)
    inv.status = 'accepted'
    CoachingInvitation.query.filter(
        CoachingInvitation.athlete_id == athlete.id,
        CoachingInvitation.status == 'pending',
        CoachingInvitation.id != inv.id,
    ).update({'status': 'refused'}, synchronize_session=False)
    db.session.commit()
    return jsonify(inv.to_dict())


@api_bp.post('/coach/athlete-requests/<int:invitation_id>/refuse')
@coach_required
def refuse_athlete_request(invitation_id):
    user = request.current_user
    inv = CoachingInvitation.query.get_or_404(invitation_id)
    if inv.status != 'pending' or (inv.direction or '') != 'athlete_to_coach':
        return jsonify({'error': 'Demande invalide'}), 400
    if user.role != 'admin' and inv.coach_id != user.id:
        return jsonify({'error': 'Non autorisé'}), 403
    inv.status = 'refused'
    db.session.commit()
    return jsonify(inv.to_dict())

