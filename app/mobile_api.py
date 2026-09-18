from datetime import datetime, date, timedelta
import re
import threading

from flask import Blueprint, current_app, request, jsonify

from app.tonnage import effective_load_kg, series_tonnage
from app import db
from app.mobile_auth import generate_token, login_required, coach_required, admin_required
from app.models import (
    User, Availability, Program, ProgramSession, ExerciseEntry,
    JournalEntry, PerformanceEntry, Exercise, Food, MealPlan, MealEntry,
    MealEntryEquivalent, Objective, MobileWeeklyBilanMarking, CoachingInvitation,
    BankChangeRequest, MUSCLE_GROUPS, WeeklyBilanMarking, SubscriptionPayment,
    SecurityEvent, CoachAthletePrivateNote,
)
from app.auth_security import (
    honeypot_triggered, hit, looks_like_bot_identity, rate_limited,
    LOGIN_LIMIT, LOGIN_WINDOW_SEC, REGISTER_LIMIT, REGISTER_WINDOW_SEC,
    SEARCH_LIMIT, SEARCH_WINDOW_SEC,
)
from app.security_events import log_security_event
import json

api_bp = Blueprint('api', __name__)

# Seed démo (~400 perfs + journal) : ne jamais bloquer deux fois le même coach.
_demo_seed_lock = threading.Lock()
_demo_seed_in_flight = set()

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _normalize_email(value):
    return (value or '').strip().lower() or None


def _is_valid_email(value):
    return bool(value and _EMAIL_RE.match(value))


def _find_user_by_login(login):
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
    """True admin only for global staff privileges. Coaches are NOT staff."""
    u = user or request.current_user
    return u.role == 'admin'


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


def _deny_manage(target_id=None, reason='authz_denied'):
    log_security_event(
        reason,
        severity='warning',
        detail={
            'target_id': target_id,
            'actor_role': getattr(request.current_user, 'role', None),
            'actor_id': getattr(request.current_user, 'id', None),
        },
        user_id=getattr(request.current_user, 'id', None),
    )
    return jsonify({'error': 'Accès refusé'}), 403


def _mask_email(email):
    if not email or '@' not in email:
        return None
    local, domain = email.split('@', 1)
    if len(local) <= 2:
        masked = (local[:1] if local else '*') + '***'
    else:
        masked = local[0] + '***' + local[-1]
    return f'{masked}@{domain}'


def _athlete_search_dict(athlete):
    """Payload recherche coach : pas d'email complet (anti-énumération)."""
    return {
        'id': athlete.id,
        'username': athlete.username,
        'email': _mask_email(athlete.email or athlete.username),
        'display_name': athlete.display_name or athlete.username,
        'role': 'athlete',
        'coach_id': None,
        'is_demo': bool(athlete.is_demo),
    }


def _personal_name_suffix(user):
    return f' ({user.username})'


def _ensure_personal_name(name, user):
    suffix = _personal_name_suffix(user)
    name = (name or '').strip()
    if not name.endswith(suffix):
        name = f'{name}{suffix}'
    return name


def _public_name_from_personal(name, user=None):
    """Retire le suffixe perso ` (username)` pour proposer un nom banque commune."""
    name = (name or '').strip()
    if user is not None:
        suffix = _personal_name_suffix(user)
        if name.endswith(suffix):
            return name[: -len(suffix)].strip() or name
    if name.endswith(')') and ' (' in name:
        return name.rsplit(' (', 1)[0].strip() or name
    return name


def _queue_promote_to_common(kind, target, requester):
    """Crée (ou réutilise) une demande Superadmin pour publier une entrée perso en commune."""
    if target is None or getattr(target, 'owner_id', None) is None:
        return None
    pending = (
        BankChangeRequest.query.filter_by(
            kind=kind, target_id=target.id, status='pending', requester_id=requester.id,
        ).all()
    )
    for row in pending:
        try:
            payload = json.loads(row.payload or '{}')
        except (TypeError, ValueError):
            payload = {}
        if payload.get('action') == 'promote_to_common':
            return row

    public_name = _public_name_from_personal(target.name, requester)
    if kind == 'exercise':
        payload = {
            'action': 'promote_to_common',
            'name': public_name,
            'muscle_group': target.muscle_group,
            'animation_slug': target.animation_slug,
            'youtube_url': target.youtube_url,
            'custom_gif_url': target.custom_gif_url,
            'media_status': 'approved' if (target.youtube_url or target.custom_gif_url or target.animation_slug) else 'none',
        }
    else:
        payload = {
            'action': 'promote_to_common',
            'name': public_name,
            'brand': target.brand,
            'kcal': target.kcal,
            'proteins': target.proteins,
            'lipids': target.lipids,
            'saturated_fats': target.saturated_fats,
            'carbs': target.carbs,
            'simple_sugars': target.simple_sugars,
            'fiber': target.fiber,
            'salt': target.salt,
        }
    req = BankChangeRequest(
        kind=kind,
        target_id=target.id,
        requester_id=requester.id,
        payload=json.dumps(payload, ensure_ascii=False),
        message='Publication en banque commune',
        status='pending',
    )
    db.session.add(req)
    db.session.flush()
    return req


def _promote_personal_to_common(kind, target, payload):
    """
    Publie une copie commune (owner_id=None). L'entrée perso reste intacte
    pour ne pas casser les programmes qui pointent déjà dessus.
    Returns (common_entry, error_response_or_None)
    """
    if target.owner_id is None:
        return target, None
    public_name = (payload.get('name') or '').strip() or _public_name_from_personal(target.name)
    if kind == 'exercise':
        muscle = payload.get('muscle_group') or target.muscle_group
        if muscle not in MUSCLE_GROUPS:
            return None, (jsonify({'error': 'muscle_group invalide'}), 400)
        existing = Exercise.query.filter_by(name=public_name).first()
        if existing:
            if existing.owner_id is None:
                # Fusionne les médias proposés sur la commune déjà existante
                slug = payload.get('animation_slug') or target.animation_slug
                yt = payload.get('youtube_url') or target.youtube_url
                gif = payload.get('custom_gif_url') or target.custom_gif_url
                if slug:
                    existing.animation_slug = slug
                if yt:
                    existing.youtube_url = yt
                if gif:
                    existing.custom_gif_url = gif
                if existing.animation_slug or existing.youtube_url or existing.custom_gif_url:
                    existing.media_status = 'approved'
                return existing, None
            return None, (jsonify({'error': f'Nom « {public_name} » déjà pris (perso)'}), 409)
        common = Exercise(
            name=public_name,
            muscle_group=muscle,
            owner_id=None,
            animation_slug=payload.get('animation_slug') or target.animation_slug,
            youtube_url=payload.get('youtube_url') or target.youtube_url,
            custom_gif_url=payload.get('custom_gif_url') or target.custom_gif_url,
            media_status=(
                payload.get('media_status')
                or (
                    'approved'
                    if (payload.get('youtube_url') or payload.get('custom_gif_url') or payload.get('animation_slug')
                        or target.youtube_url or target.custom_gif_url or target.animation_slug)
                    else 'none'
                )
            ),
        )
        db.session.add(common)
        db.session.flush()
        return common, None

    existing = Food.query.filter_by(name=public_name).first()
    if existing:
        if existing.owner_id is None:
            return existing, None
        return None, (jsonify({'error': f'Nom « {public_name} » déjà pris (perso)'}), 409)
    common = Food(
        name=public_name,
        brand=payload.get('brand', target.brand),
        kcal=payload['kcal'] if payload.get('kcal') is not None else target.kcal,
        proteins=payload.get('proteins', target.proteins),
        lipids=payload.get('lipids', target.lipids),
        saturated_fats=payload.get('saturated_fats', target.saturated_fats),
        carbs=payload['carbs'] if payload.get('carbs') is not None else target.carbs,
        simple_sugars=payload.get('simple_sugars', target.simple_sugars),
        fiber=payload.get('fiber', target.fiber),
        salt=payload.get('salt', target.salt),
        owner_id=None,
    )
    db.session.add(common)
    db.session.flush()
    return common, None


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


def _coach_quota_count(coach_id):
    """Athlètes comptés dans l'abonnement : l'athlète de démo est offert."""
    return _coach_team_query(coach_id).filter(User.is_demo.isnot(True)).count()


def _ensure_demo_athlete_safe(coach, *, background=True):
    """Athlète de démo du coach — un échec de seed ne doit jamais casser l'écran.

    Le seed (~400 perfs + journal) est trop lourd pour le chemin HTTP sync :
    gunicorn abort le worker (SystemExit) et le mobile voit Network Error.
    Toujours préférer background=True (register / dashboard / list athletes).
    """
    if coach is None or getattr(coach, 'role', None) != 'coach':
        return None

    if coach.demo_seeded_at is not None:
        try:
            from app.demo_athlete import demo_athlete_of
            return demo_athlete_of(coach.id)
        except Exception:
            return None

    if not background:
        try:
            from app.demo_athlete import ensure_demo_athlete
            return ensure_demo_athlete(coach)
        except Exception:
            db.session.rollback()
            return None

    coach_id = int(coach.id)
    with _demo_seed_lock:
        if coach_id in _demo_seed_in_flight:
            return None
        _demo_seed_in_flight.add(coach_id)

    app = current_app._get_current_object()

    def _run():
        try:
            with app.app_context():
                from app.demo_athlete import ensure_demo_athlete
                c = User.query.get(coach_id)
                if c is not None and c.demo_seeded_at is None:
                    ensure_demo_athlete(c)
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
        finally:
            with _demo_seed_lock:
                _demo_seed_in_flight.discard(coach_id)

    threading.Thread(target=_run, name=f'demo-seed-{coach_id}', daemon=True).start()
    return None


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
    # Les athlètes de démo du compte n'ont aucune raison de survivre à leur coach.
    for demo in User.query.filter_by(role='athlete', coach_id=user_id, is_demo=True).all():
        _purge_user_data(demo.id)
        db.session.delete(demo)

    CoachingInvitation.query.filter(
        (CoachingInvitation.coach_id == user_id) | (CoachingInvitation.athlete_id == user_id)
    ).delete(synchronize_session=False)
    User.query.filter_by(coach_id=user_id).update(
        {'coach_id': None, 'coach_associated_at': None}, synchronize_session=False,
    )

    # Bibliothèque templates du coach
    for tmpl in Program.query.filter_by(coach_id=user_id, is_template=True).all():
        db.session.delete(tmpl)
    for tmpl in MealPlan.query.filter_by(coach_id=user_id, is_template=True).all():
        db.session.delete(tmpl)
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
    try:
        WeeklyBilanMarking.query.filter(
            (WeeklyBilanMarking.coach_id == user_id) | (WeeklyBilanMarking.athlete_id == user_id)
        ).delete(synchronize_session=False)
    except Exception:
        pass
    try:
        SubscriptionPayment.query.filter(
            (SubscriptionPayment.user_id == user_id) | (SubscriptionPayment.resolved_by_id == user_id)
        ).delete(synchronize_session=False)
    except Exception:
        pass
    JournalEntry.query.filter_by(athlete_id=user_id).delete(synchronize_session=False)
    PerformanceEntry.query.filter_by(athlete_id=user_id).delete(synchronize_session=False)
    Objective.query.filter_by(athlete_id=user_id).delete(synchronize_session=False)
    BankChangeRequest.query.filter(
        (BankChangeRequest.requester_id == user_id) | (BankChangeRequest.reviewed_by_id == user_id)
    ).delete(synchronize_session=False)
    Exercise.query.filter_by(owner_id=user_id).delete(synchronize_session=False)
    Food.query.filter_by(owner_id=user_id).delete(synchronize_session=False)


def _athlete_summary_batch(athletes):
    """Résumé dashboard coach : 2 requêtes agrégées (+ la liste athlètes = ≤3)."""
    from sqlalchemy import func, literal, union_all

    if not athletes:
        return []
    athlete_ids = [a.id for a in athletes]

    last_journal_rows = (
        db.session.query(JournalEntry.athlete_id, func.max(JournalEntry.entry_date))
        .filter(JournalEntry.athlete_id.in_(athlete_ids))
        .group_by(JournalEntry.athlete_id)
        .all()
    )
    last_by_id = {aid: d for aid, d in last_journal_rows}

    obj_q = (
        db.session.query(
            Objective.athlete_id.label('aid'),
            literal('obj').label('kind'),
            func.count(Objective.id).label('cnt'),
        )
        .filter(Objective.athlete_id.in_(athlete_ids))
        .group_by(Objective.athlete_id)
    )
    prog_q = (
        db.session.query(
            Program.athlete_id.label('aid'),
            literal('prog').label('kind'),
            func.count(Program.id).label('cnt'),
        )
        .filter(Program.athlete_id.in_(athlete_ids))
        .group_by(Program.athlete_id)
    )
    count_rows = db.session.execute(union_all(obj_q, prog_q)).all()
    obj_by_id = {}
    prog_by_id = {}
    for aid, kind, cnt in count_rows:
        if kind == 'obj':
            obj_by_id[aid] = int(cnt)
        else:
            prog_by_id[aid] = int(cnt)

    out = []
    for athlete in athletes:
        last = last_by_id.get(athlete.id)
        out.append({
            'athlete': athlete.to_dict(),
            'last_journal_date': last.isoformat() if last else None,
            'objectives_count': obj_by_id.get(athlete.id, 0),
            'programs_count': prog_by_id.get(athlete.id, 0),
        })
    return out


def _athlete_summary(athlete):
    """Compat mono-athlète (évite N+1 si appelé en boucle — préférer batch)."""
    return _athlete_summary_batch([athlete])[0]


def _enforce_coach_quota_or_trim(coach, prefer_keep_ids=None):
    limit = coach.athlete_limit()
    if limit is None:
        return []
    athletes = (
        _coach_team_query(coach.id)
        .filter(User.is_demo.isnot(True))
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
                _snapshot_athlete_content_to_coach_library(coach.id, a)
                _link_athlete_to_coach(a, None)
                removed.append(a.id)
        return removed
    removed = []
    for a in athletes[limit:]:
        _snapshot_athlete_content_to_coach_library(coach.id, a)
        _link_athlete_to_coach(a, None)
        removed.append(a.id)
    return removed



def _clone_program(source, *, athlete_id, coach_id, name, is_template=False):
    """Deep-copy sessions/exercises. Ne commit pas."""
    new_program = Program(
        name=(name or source.name).strip()[:128],
        athlete_id=athlete_id,
        coach_id=coach_id,
        is_active=False,
        is_template=bool(is_template),
    )
    db.session.add(new_program)
    db.session.flush()
    for sess in source.sessions:
        new_session = ProgramSession(
            program_id=new_program.id,
            day_of_week=sess.day_of_week,
            session_name=sess.session_name,
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
    return new_program


def _copy_meal_entries_with_equivalents(source_meals, target_plan_id):
    """Copie les entrées + équivalents vers un plan cible (déjà flushé)."""
    for meal in source_meals:
        new_entry = MealEntry(
            meal_plan_id=target_plan_id, food_id=meal.food_id, meal_number=meal.meal_number,
            quantity=meal.quantity, position=meal.position,
        )
        db.session.add(new_entry)
        db.session.flush()
        for eq in (meal.equivalents or []):
            db.session.add(MealEntryEquivalent(
                meal_entry_id=new_entry.id,
                food_id=eq.food_id,
                quantity=eq.quantity,
            ))


def _clone_meal_plan(source, *, athlete_id, coach_id, name, is_template=False):
    """Deep-copy meals + times/labels + équivalents. Ne commit pas."""
    new_plan = MealPlan(
        name=(name or source.name).strip()[:128],
        athlete_id=athlete_id,
        coach_id=coach_id,
        is_active=False,
        is_template=bool(is_template),
        meal_count=source.meal_count,
        **{f'meal_time_{i}': getattr(source, f'meal_time_{i}') for i in range(1, 7)},
        **{f'meal_label_{i}': getattr(source, f'meal_label_{i}') for i in range(1, 7)},
    )
    db.session.add(new_plan)
    db.session.flush()
    _copy_meal_entries_with_equivalents(source.meals, new_plan.id)
    return new_plan


def _set_meal_entry_equivalents(entry, items):
    """Remplace les équivalents d'une entrée. `items` = [{food_id, quantity}, ...]."""
    try:
        MealEntryEquivalent.query.filter_by(meal_entry_id=entry.id).delete()
    except Exception:
        db.session.rollback()
        try:
            db.create_all()
            MealEntryEquivalent.query.filter_by(meal_entry_id=entry.id).delete()
        except Exception:
            db.session.rollback()
            raise
    seen = set()
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        try:
            food_id = int(raw.get('food_id'))
        except (TypeError, ValueError):
            continue
        if food_id == entry.food_id or food_id in seen:
            continue
        food = Food.query.get(food_id)
        if food is None:
            continue
        try:
            qty = float(raw.get('quantity') or 100)
        except (TypeError, ValueError):
            qty = 100.0
        qty = max(1.0, min(2000.0, qty))
        seen.add(food_id)
        db.session.add(MealEntryEquivalent(
            meal_entry_id=entry.id,
            food_id=food_id,
            quantity=qty,
        ))
    db.session.flush()
    return entry


def _library_version_name(base_name, athlete, day):
    label = (athlete.display_name or athlete.username or 'athlète').strip()[:32]
    return f'{base_name} · {label} · {day.strftime("%d/%m/%Y")}'[:128]


def _replace_program_template_from_source(target, source):
    for sess in list(target.sessions):
        db.session.delete(sess)
    db.session.flush()
    for sess in source.sessions:
        new_session = ProgramSession(
            program_id=target.id,
            day_of_week=sess.day_of_week,
            session_name=sess.session_name,
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


def _replace_meal_plan_template_from_source(target, source):
    for meal in list(target.meals):
        db.session.delete(meal)
    target.meal_count = source.meal_count
    for i in range(1, 7):
        setattr(target, f'meal_time_{i}', getattr(source, f'meal_time_{i}'))
        setattr(target, f'meal_label_{i}', getattr(source, f'meal_label_{i}'))
    db.session.flush()
    for meal in source.meals:
        new_entry = MealEntry(
            meal_plan_id=target.id, food_id=meal.food_id, meal_number=meal.meal_number,
            quantity=meal.quantity, position=meal.position,
        )
        db.session.add(new_entry)
        db.session.flush()
        for eq in (meal.equivalents or []):
            db.session.add(MealEntryEquivalent(
                meal_entry_id=new_entry.id,
                food_id=eq.food_id,
                quantity=eq.quantity,
            ))


def _sync_program_to_coach_library(program, *, actor=None, force=False):
    if not program or getattr(program, 'is_template', False) or not program.athlete_id:
        return None
    if not force:
        actor = actor or getattr(request, 'current_user', None)
        if not actor or actor.role not in ('coach', 'admin'):
            return None
    athlete = User.query.get(program.athlete_id)
    if not athlete or getattr(athlete, 'is_demo', False):
        return None
    coach_id = program.coach_id or athlete.coach_id
    if not coach_id:
        return None
    if not program.coach_id:
        program.coach_id = int(coach_id)
    day = date.today()
    name = _library_version_name(program.name, athlete, day)
    existing = Program.query.filter_by(
        coach_id=int(coach_id),
        is_template=True,
        library_source_id=program.id,
        library_day=day,
    ).first()
    if existing:
        _replace_program_template_from_source(existing, program)
        existing.name = name
        existing.updated_at = datetime.utcnow()
        return existing
    tmpl = _clone_program(
        program, athlete_id=None, coach_id=int(coach_id), name=name, is_template=True,
    )
    tmpl.library_source_id = program.id
    tmpl.library_day = day
    return tmpl


def _sync_meal_plan_to_coach_library(plan, *, actor=None, force=False):
    if not plan or getattr(plan, 'is_template', False) or not plan.athlete_id:
        return None
    if not force:
        actor = actor or getattr(request, 'current_user', None)
        if not actor or actor.role not in ('coach', 'admin'):
            return None
    athlete = User.query.get(plan.athlete_id)
    if not athlete or getattr(athlete, 'is_demo', False):
        return None
    coach_id = plan.coach_id or athlete.coach_id
    if not coach_id:
        return None
    if not plan.coach_id:
        plan.coach_id = int(coach_id)
    day = date.today()
    name = _library_version_name(plan.name, athlete, day)
    existing = MealPlan.query.filter_by(
        coach_id=int(coach_id),
        is_template=True,
        library_source_id=plan.id,
        library_day=day,
    ).first()
    if existing:
        _replace_meal_plan_template_from_source(existing, plan)
        existing.name = name
        return existing
    tmpl = _clone_meal_plan(
        plan, athlete_id=None, coach_id=int(coach_id), name=name, is_template=True,
    )
    tmpl.library_source_id = plan.id
    tmpl.library_day = day
    return tmpl


def _snapshot_athlete_content_to_coach_library(coach_id, athlete):
    """Dernière version du jour (ou création) avant détachement."""
    if not coach_id or not athlete or getattr(athlete, 'is_demo', False):
        return 0
    n = 0
    # Ne pas exiger program.coach_id : les anciens programmes l’ont souvent à NULL.
    programs = Program.query.filter_by(athlete_id=athlete.id, is_template=False).all()
    for p in programs:
        if p.coach_id not in (None, int(coach_id)):
            continue
        if _sync_program_to_coach_library(p, force=True):
            n += 1
    plans = MealPlan.query.filter_by(athlete_id=athlete.id, is_template=False).all()
    for plan in plans:
        if plan.coach_id not in (None, int(coach_id)):
            continue
        if _sync_meal_plan_to_coach_library(plan, force=True):
            n += 1
    return n


def _backfill_coach_library(coach):
    """Importe les progs / diètes actuels de l’équipe dans la bibliothèque (1 version / jour)."""
    if not coach or coach.role not in ('coach', 'admin'):
        return 0
    try:
        coach_id = int(coach.id)
        n = 0
        athletes = (
            _coach_team_query(coach_id)
            .filter(User.is_demo.isnot(True))
            .all()
        )
        for athlete in athletes:
            n += _snapshot_athlete_content_to_coach_library(coach_id, athlete)
        if n:
            db.session.commit()
        return n
    except Exception:
        db.session.rollback()
        return 0


def _can_access_program(program, user=None):
    user = user or request.current_user
    if getattr(program, 'is_template', False):
        if user.role == 'admin':
            return True
        return user.role == 'coach' and program.coach_id == user.id
    if program.athlete_id is None:
        return False
    return _can_manage_athlete(program.athlete_id, user)


def _can_access_meal_plan(plan, user=None):
    user = user or request.current_user
    if getattr(plan, 'is_template', False):
        if user.role == 'admin':
            return True
        return user.role == 'coach' and plan.coach_id == user.id
    if plan.athlete_id is None:
        return False
    return _can_manage_athlete(plan.athlete_id, user)



# ---------------------------------------------------------------- AUTH -----

@api_bp.post('/auth/login')
def login():
    if rate_limited('login', limit=LOGIN_LIMIT, window_sec=LOGIN_WINDOW_SEC):
        log_security_event('rate_limit_login', severity='warning', detail={'action': 'login'})
        return jsonify({'error': 'Trop de tentatives. Réessaie dans quelques minutes.'}), 429
    data = request.get_json(silent=True) or {}
    login_id = (data.get('username') or data.get('email') or '').strip()
    password = data.get('password') or ''

    user = _find_user_by_login(login_id)
    if not user or not user.check_password(password):
        hit('login')
        log_security_event(
            'login_failed',
            severity='warning',
            detail={'login': (login_id or '')[:120]},
            user_id=user.id if user else None,
        )
        return jsonify({'error': 'Identifiants incorrects'}), 401

    token = generate_token(user)
    return jsonify({'token': token, 'user': user.to_dict()})


@api_bp.post('/auth/register')
def register():
    """Inscription autonome — athlète ou coach (pas admin)."""
    if rate_limited('register', limit=REGISTER_LIMIT, window_sec=REGISTER_WINDOW_SEC):
        log_security_event('rate_limit_register', severity='warning', detail={'action': 'register'})
        return jsonify({'error': 'Trop d’inscriptions depuis cette adresse. Réessaie plus tard.'}), 429

    data = request.get_json(silent=True) or {}
    if honeypot_triggered(data):
        hit('register')
        log_security_event(
            'honeypot_register',
            severity='critical',
            detail={'keys': [k for k in ('website', 'company', 'url', 'hp_field', 'fax') if data.get(k)]},
        )
        return jsonify({'error': 'Inscription refusée'}), 400

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
    if len(password) < 8:
        return jsonify({'error': 'Mot de passe trop court (8 caractères min.)'}), 400
    if looks_like_bot_identity(email, display_name):
        hit('register')
        log_security_event(
            'bot_identity_register',
            severity='critical',
            detail={'email': email[:120], 'display_name': display_name[:80]},
        )
        return jsonify({'error': 'Inscription refusée'}), 400
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
        subscription_tier=0,
        independent_module=False,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    if role == 'coach':
        # Synchrone à l'inscription : le coach voit Alex Démo dès le 1er dashboard.
        # Background : le seed sync faisait planter gunicorn à l'inscription.
        _ensure_demo_athlete_safe(user)
    hit('register')
    token = generate_token(user)
    return jsonify({'token': token, 'user': user.to_dict()}), 201


@api_bp.get('/auth/me')
@login_required
def me():
    return jsonify(request.current_user.to_dict())


@api_bp.post('/auth/me/avatar')
@login_required
def upload_my_avatar():
    """Photo de profil (athlète ou coach) — multipart `avatar` ou `file`."""
    from app.avatar_media import delete_avatar_file, save_avatar_upload
    from app.exercise_media import public_absolute_url

    user = request.current_user
    upload = request.files.get('avatar') or request.files.get('file') or request.files.get('photo')
    if not upload or not upload.filename:
        return jsonify({'error': 'Fichier image requis (avatar)'}), 400
    try:
        relative = save_avatar_upload(upload)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    old = user.avatar_url
    user.avatar_url = relative
    db.session.commit()
    if old and old != relative:
        delete_avatar_file(old)
    return jsonify({
        'ok': True,
        'avatar_url': public_absolute_url(relative),
        'user': user.to_dict(),
    })


@api_bp.delete('/auth/me/avatar')
@login_required
def delete_my_avatar():
    from app.avatar_media import delete_avatar_file

    user = request.current_user
    if user.avatar_url:
        delete_avatar_file(user.avatar_url)
        user.avatar_url = None
        db.session.commit()
    return jsonify({'ok': True, 'avatar_url': None, 'user': user.to_dict()})


@api_bp.post('/auth/me/logo')
@login_required
@coach_required
def upload_my_logo():
    """Logo coach (marque / salle) — multipart `logo` ou `file`."""
    from app.avatar_media import delete_avatar_file, save_avatar_upload
    from app.exercise_media import public_absolute_url

    user = request.current_user
    upload = request.files.get('logo') or request.files.get('file') or request.files.get('image')
    if not upload or not upload.filename:
        return jsonify({'error': 'Fichier image requis (logo)'}), 400
    try:
        relative = save_avatar_upload(upload)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    old = user.logo_url
    user.logo_url = relative
    db.session.commit()
    if old and old != relative:
        delete_avatar_file(old)
    return jsonify({
        'ok': True,
        'logo_url': public_absolute_url(relative),
        'user': user.to_dict(),
    })


@api_bp.delete('/auth/me/logo')
@login_required
@coach_required
def delete_my_logo():
    from app.avatar_media import delete_avatar_file

    user = request.current_user
    if user.logo_url:
        delete_avatar_file(user.logo_url)
        user.logo_url = None
        db.session.commit()
    return jsonify({'ok': True, 'logo_url': None, 'user': user.to_dict()})


@api_bp.get('/media/avatars/<path:filename>')
def serve_avatar_media(filename):
    from flask import send_from_directory
    from app.avatar_media import avatar_storage_dir, is_safe_avatar_filename

    if not is_safe_avatar_filename(filename):
        return jsonify({'error': 'Fichier invalide'}), 400
    return send_from_directory(avatar_storage_dir(), filename)


# ------------------------------------------------------------- DASHBOARD ---

@api_bp.get('/dashboard')
@login_required
def dashboard():
    user = request.current_user
    today = date.today()

    if user.role in ('coach', 'admin'):
        _ensure_demo_athlete_safe(user)
        # Toujours l'équipe du compte connecté (admin plateforme gère le reste via /admin/users).
        athletes = _coach_team_query(user.id).order_by(User.username).all()
        summary = _athlete_summary_batch(athletes)
        limit = user.athlete_limit() if user.role == 'coach' else None
        quota_count = sum(1 for a in athletes if not a.is_demo)
        over_quota = bool(user.role == 'coach' and limit is not None and quota_count > limit)
        return jsonify({
            'role': user.role,
            'athletes': summary,
            'subscription_tier': int(user.subscription_tier or 0) if user.role == 'coach' else None,
            'athlete_limit': limit,
            'athlete_count': len(athletes),
            'quota_count': quota_count,
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
        sessions = sorted(program.sessions, key=lambda s: s.day_of_week)
        session_ids = [s.id for s in sessions]
        last_by_session = {}
        if session_ids:
            from sqlalchemy import func
            rows = (
                db.session.query(
                    PerformanceEntry.program_session_id,
                    func.max(PerformanceEntry.entry_date),
                )
                .filter(
                    PerformanceEntry.athlete_id == user.id,
                    PerformanceEntry.program_session_id.in_(session_ids),
                )
                .group_by(PerformanceEntry.program_session_id)
                .all()
            )
            last_by_session = {sid: d for sid, d in rows if sid is not None}
        for s in sessions:
            last_date = last_by_session.get(s.id)
            week_sessions.append({
                'id': s.id,
                'day_of_week': s.day_of_week,
                'session_name': s.session_name,
                'exercise_count': len(s.exercises),
                'is_today': s.day_of_week == today.weekday(),
                'last_logged_date': last_date.isoformat() if last_date else None,
            })

    objectives = Objective.query.filter_by(athlete_id=user.id).order_by(Objective.created_at.desc()).limit(5).all()
    last_journal = (JournalEntry.query.filter_by(athlete_id=user.id)
                     .order_by(JournalEntry.entry_date.desc()).first())
    today_journal = JournalEntry.query.filter_by(athlete_id=user.id, entry_date=today).first()
    pending_invites = (
        CoachingInvitation.query.filter(
            CoachingInvitation.athlete_id == user.id,
            CoachingInvitation.status == 'pending',
            # Ne pas remonter les demandes initiées par l'athlète (côté coach).
            CoachingInvitation.direction == 'coach_to_athlete',
        )
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
        'bilan_note_questions': user.get_bilan_note_questions(enabled_only=True),
        'athlete_note': marking.note_dict() if marking else None,
        'week_start': current_week_start.isoformat(),
    })


# ---------------------------------------------------------------- COACH ----

@api_bp.get('/coach/athletes')
@coach_required
def list_athletes():
    user = request.current_user
    _ensure_demo_athlete_safe(user)
    athletes = _coach_team_query(user.id).order_by(User.username).all()
    return jsonify([a.to_dict() for a in athletes])


@api_bp.get('/coach/athletes/search')
@coach_required
def search_athletes():
    if rate_limited('athlete_search', limit=SEARCH_LIMIT, window_sec=SEARCH_WINDOW_SEC):
        log_security_event(
            'rate_limit_athlete_search',
            severity='warning',
            detail={'action': 'athlete_search'},
            user_id=request.current_user.id,
        )
        return jsonify({'error': 'Trop de recherches. Réessaie dans quelques minutes.'}), 429
    hit('athlete_search')

    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify([])

    # Email : exact match uniquement (anti-énumération par préfixe).
    email_q = _normalize_email(q)
    if _is_valid_email(email_q):
        row = (
            User.query.filter(
                User.role == 'athlete',
                User.coach_id.is_(None),
                User.is_demo.isnot(True),
                db.or_(
                    db.func.lower(User.email) == email_q,
                    db.func.lower(User.username) == email_q,
                ),
            ).first()
        )
        return jsonify([_athlete_search_dict(row)] if row else [])

    # Préfixe email (contient @ mais pas une adresse complète) → pas de résultats.
    if '@' in q:
        return jsonify([])

    like = f'%{q}%'
    rows = (
        User.query.filter(
            User.role == 'athlete',
            User.coach_id.is_(None),
            User.is_demo.isnot(True),
            db.or_(
                User.display_name.ilike(like),
                User.username.ilike(like),
            ),
        )
        .order_by(User.display_name, User.username)
        .limit(20)
        .all()
    )
    # Pattern suspect : requêtes très courtes répétées déjà rate-limitées ;
    # log si beaucoup de résultats pour une query générique.
    if len(q) <= 2 and len(rows) >= 10:
        log_security_event(
            'suspicious_athlete_search',
            severity='info',
            detail={'q': q[:40], 'hits': len(rows)},
            user_id=request.current_user.id,
        )
    return jsonify([_athlete_search_dict(a) for a in rows])


@api_bp.delete('/coach/athletes/<int:athlete_id>/unlink')
@coach_required
def unlink_athlete(athlete_id):
    user = request.current_user
    athlete = User.query.get_or_404(athlete_id)
    if athlete.role != 'athlete':
        return jsonify({'error': 'Utilisateur non modifiable'}), 400
    if user.role == 'coach' and athlete.coach_id != user.id:
        return jsonify({'error': "Cet athlète n'est pas dans ton équipe"}), 403
    if athlete.is_demo:
        # Compte fictif : on le supprime pour de bon (demo_seeded_at évite qu'il revienne).
        _purge_user_data(athlete.id)
        db.session.delete(athlete)
        db.session.commit()
        return jsonify({'ok': True, 'deleted': True})
    coach_id_for_snap = athlete.coach_id
    if user.role == 'coach':
        coach_id_for_snap = user.id
    _snapshot_athlete_content_to_coach_library(coach_id_for_snap, athlete)
    _link_athlete_to_coach(athlete, None)
    if user.role == 'coach':
        CoachingInvitation.query.filter_by(
            coach_id=user.id, athlete_id=athlete_id, status='pending',
        ).update({'status': 'refused'}, synchronize_session=False)
    db.session.commit()
    return jsonify({'ok': True})


@api_bp.get('/coach/library/programs')
@coach_required
def list_coach_program_library():
    user = request.current_user
    _backfill_coach_library(user)
    q = Program.query.filter_by(is_template=True)
    if user.role == 'coach':
        q = q.filter_by(coach_id=user.id)
    programs = q.order_by(Program.created_at.desc()).all()
    return jsonify([p.to_dict(with_sessions=False) for p in programs])


@api_bp.post('/coach/library/programs/<int:program_id>/assign')
@coach_required
def assign_library_program(program_id):
    source = Program.query.get_or_404(program_id)
    if not source.is_template or not _can_access_program(source):
        return jsonify({'error': 'Modèle introuvable'}), 404
    data = request.get_json(silent=True) or {}
    athlete_id = data.get('athlete_id')
    if not athlete_id:
        return jsonify({'error': 'athlete_id requis'}), 400
    athlete_id = int(athlete_id)
    if not _can_manage_athlete(athlete_id):
        return _deny_manage()
    name = (data.get('name') or source.name).strip()
    new_program = _clone_program(
        source, athlete_id=athlete_id, coach_id=_coach_id_for_create(athlete_id),
        name=name, is_template=False,
    )
    db.session.flush()
    _sync_program_to_coach_library(new_program)
    db.session.commit()
    return jsonify(new_program.to_dict(with_sessions=True)), 201


@api_bp.get('/coach/library/meal-plans')
@coach_required
def list_coach_meal_plan_library():
    user = request.current_user
    _backfill_coach_library(user)
    q = MealPlan.query.filter_by(is_template=True)
    if user.role == 'coach':
        q = q.filter_by(coach_id=user.id)
    plans = q.order_by(MealPlan.created_at.desc()).all()
    return jsonify([p.to_dict(with_meals=False) for p in plans])


@api_bp.post('/coach/library/meal-plans/<int:plan_id>/assign')
@coach_required
def assign_library_meal_plan(plan_id):
    source = MealPlan.query.get_or_404(plan_id)
    if not source.is_template or not _can_access_meal_plan(source):
        return jsonify({'error': 'Modèle introuvable'}), 404
    data = request.get_json(silent=True) or {}
    athlete_id = data.get('athlete_id')
    if not athlete_id:
        return jsonify({'error': 'athlete_id requis'}), 400
    athlete_id = int(athlete_id)
    if not _can_manage_athlete(athlete_id):
        return _deny_manage()
    name = (data.get('name') or source.name).strip()
    new_plan = _clone_meal_plan(
        source, athlete_id=athlete_id, coach_id=_coach_id_for_create(athlete_id),
        name=name, is_template=False,
    )
    db.session.flush()
    _sync_meal_plan_to_coach_library(new_plan)
    db.session.commit()
    return jsonify(new_plan.to_dict()), 201


@api_bp.post('/coach/quota/resolve')
@coach_required
def resolve_quota():
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
    current_count = _coach_quota_count(user.id)
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
        CoachingInvitation.query.filter(
            CoachingInvitation.athlete_id == user.id,
            CoachingInvitation.status == 'pending',
            CoachingInvitation.direction == 'coach_to_athlete',
        )
        .order_by(CoachingInvitation.created_at.desc()).all()
    )
    return jsonify([i.to_dict() for i in rows])


@api_bp.post('/athlete/invitations/<int:invitation_id>/accept')
@login_required
def accept_invitation(invitation_id):
    user = request.current_user
    if user.role != 'athlete':
        return jsonify({'error': "Réservé à l'athlète"}), 403
    inv = CoachingInvitation.query.get_or_404(invitation_id)
    if inv.athlete_id != user.id or inv.status != 'pending':
        return jsonify({'error': 'Invitation invalide'}), 400
    if (inv.direction or 'coach_to_athlete') != 'coach_to_athlete':
        return jsonify({'error': 'Cette demande doit être acceptée par le coach'}), 400
    if user.coach_id:
        return jsonify({'error': 'Tu as déjà un coach'}), 409
    coach = User.query.get(inv.coach_id)
    if not coach or coach.role != 'coach':
        return jsonify({'error': 'Coach introuvable'}), 404
    limit = coach.athlete_limit()
    if limit is not None and _coach_quota_count(coach.id) >= limit:
        if limit == 0:
            return jsonify({
                'error': "Ce coach n'a pas d'abonnement actif pour accepter un athlète",
                'code': 'SUBSCRIPTION_REQUIRED',
            }), 403
        return jsonify({'error': "Ce coach a atteint son quota d'athlètes", 'code': 'QUOTA_REACHED'}), 403
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
        return jsonify({'error': "Réservé à l'athlète"}), 403
    inv = CoachingInvitation.query.get_or_404(invitation_id)
    if inv.athlete_id != user.id or inv.status != 'pending':
        return jsonify({'error': 'Invitation invalide'}), 400
    if (inv.direction or 'coach_to_athlete') != 'coach_to_athlete':
        return jsonify({'error': 'Cette demande doit être traitée par le coach'}), 400
    inv.status = 'refused'
    db.session.commit()
    return jsonify({'ok': True})


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
        return jsonify({'error': "Ce nom d'utilisateur existe déjà"}), 409

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
            _snapshot_athlete_content_to_coach_library(user.coach_id, user)
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
    if not _can_manage_athlete(obj.athlete_id):
        return _deny_manage(obj.athlete_id)
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
    if not _can_manage_athlete(obj.athlete_id):
        return _deny_manage(obj.athlete_id)
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
        Program.query.filter_by(athlete_id=athlete_id, is_template=False)
        .order_by(Program.is_active.desc(), Program.created_at.desc())
        .all()
    )
    return jsonify([p.to_dict() for p in programs])


@api_bp.get('/programs/<int:program_id>')
@login_required
def get_program(program_id):
    program = Program.query.get_or_404(program_id)
    if not _can_manage_athlete(program.athlete_id):
        return _deny_manage(program.athlete_id)
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
    has_any = Program.query.filter_by(athlete_id=athlete_id, is_template=False).count() > 0
    program = Program(
        name=name,
        athlete_id=athlete_id,
        coach_id=_coach_id_for_create(athlete_id),
        is_active=not has_any,
        is_template=False,
    )
    db.session.add(program)
    db.session.flush()
    _sync_program_to_coach_library(program)
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
    _sync_program_to_coach_library(program)
    db.session.commit()
    return jsonify(program.to_dict())


@api_bp.post('/programs/<int:program_id>/activate')
@login_required
def activate_program(program_id):
    """Mark a program as the athlete's current one (shown on home)."""
    program = Program.query.get_or_404(program_id)
    user = request.current_user
    if getattr(program, 'is_template', False) or not program.athlete_id:
        return jsonify({'error': "Impossible d'activer un modèle bibliothèque"}), 400
    if not _can_manage_athlete(program.athlete_id, user):
        return _deny_manage(program.athlete_id)
    Program.query.filter_by(athlete_id=program.athlete_id, is_active=True, is_template=False).update(
        {'is_active': False}, synchronize_session=False,
    )
    program.is_active = True
    db.session.commit()
    return jsonify(program.to_dict(with_sessions=True))


@api_bp.post('/programs/<int:program_id>/duplicate')
@login_required
def duplicate_program(program_id):
    source = Program.query.get_or_404(program_id)
    if not _can_access_program(source):
        return _deny_manage()
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or f'{source.name} (copie)').strip()
    as_template = bool(data.get('as_template'))
    user = request.current_user

    if as_template or (getattr(source, 'is_template', False) and data.get('athlete_id') is None and user.role == 'coach'):
        if user.role not in ('coach', 'admin'):
            return jsonify({'error': 'Réservé au coach'}), 403
        coach_id = user.id if user.role == 'coach' else (source.coach_id or user.id)
        new_program = _clone_program(
            source, athlete_id=None, coach_id=coach_id, name=name, is_template=True,
        )
        new_program.library_source_id = source.library_source_id or source.id
        new_program.library_day = date.today()
        db.session.commit()
        return jsonify(new_program.to_dict(with_sessions=True)), 201

    athlete_id = data.get('athlete_id') or source.athlete_id
    if not athlete_id:
        return jsonify({'error': 'athlete_id requis'}), 400
    athlete_id = int(athlete_id)
    if not _can_manage_athlete(athlete_id):
        return _deny_manage()
    new_program = _clone_program(
        source, athlete_id=athlete_id, coach_id=_coach_id_for_create(athlete_id),
        name=name, is_template=False,
    )
    db.session.flush()
    _sync_program_to_coach_library(new_program)
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
    data = session_obj.to_dict(with_exercises=True)
    for ex in data.get('exercises') or []:
        media = _resolve_exercise_media_payload(ex.get('name') or '', user)
        ex['animation_slug'] = media.get('animation_slug')
        ex['youtube_url'] = media.get('youtube_url')
        ex['custom_gif_url'] = media.get('custom_gif_url')
        ex['has_media'] = bool(media.get('has_media'))
    return jsonify(data)


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
    # Seul le Superadmin crée directement en banque commune ; sinon perso + file de publication.
    as_common = user.role == 'admin' and not bool(data.get('personal'))
    owner_id = None
    if not as_common:
        owner_id = user.id
        name = _ensure_personal_name(name, user)
    if Exercise.query.filter_by(name=name).first():
        return jsonify({'error': 'Cet exercice existe déjà'}), 409

    from app.exercise_media import normalize_youtube_url
    youtube_url = None
    try:
        youtube_url = normalize_youtube_url(data.get('youtube_url'))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    animation_slug = (data.get('animation_slug') or '').strip() or None
    custom_gif_url = (data.get('custom_gif_url') or '').strip() or None
    has_media = bool(animation_slug or youtube_url or custom_gif_url)
    if as_common:
        media_status = 'approved' if has_media else 'none'
    else:
        media_status = 'personal' if has_media else 'none'

    exercise = Exercise(
        name=name,
        muscle_group=muscle_group,
        owner_id=owner_id,
        animation_slug=animation_slug if user.role == 'admin' else None,
        youtube_url=youtube_url,
        custom_gif_url=custom_gif_url,
        media_status=media_status,
    )
    db.session.add(exercise)
    db.session.flush()
    if owner_id is not None:
        _queue_promote_to_common('exercise', exercise, user)
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
    from app.exercise_media import normalize_youtube_url
    if 'youtube_url' in data:
        try:
            exercise.youtube_url = normalize_youtube_url(data.get('youtube_url'))
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
    if 'custom_gif_url' in data and user.role == 'admin':
        exercise.custom_gif_url = (data.get('custom_gif_url') or '').strip() or None
    if 'animation_slug' in data and user.role == 'admin':
        exercise.animation_slug = (data.get('animation_slug') or '').strip() or None
    if exercise.animation_slug or exercise.youtube_url or exercise.custom_gif_url:
        if exercise.owner_id is None:
            exercise.media_status = 'approved'
        elif exercise.media_status == 'none':
            exercise.media_status = 'personal'
    else:
        exercise.media_status = 'none'
    db.session.commit()
    return jsonify(exercise.to_dict())


@api_bp.post('/exercise-bank/<int:exercise_id>/media')
@login_required
def update_exercise_bank_media(exercise_id):
    """Média YouTube / GIF : admin édite la commune ; coach édite son perso (fork si besoin)."""
    from app.exercise_media import normalize_youtube_url, save_gif_upload

    exercise = Exercise.query.get_or_404(exercise_id)
    user = request.current_user
    # JSON ou multipart
    data = request.get_json(silent=True) or {}
    form = request.form or {}

    if exercise.owner_id is None:
        if user.role == 'admin':
            # Superadmin : détache / remplace directement sur la banque partagée
            pass
        else:
            # Coach / athlète : fork perso pour poser sa propre vidéo sans toucher la commune
            base_name = _ensure_personal_name(exercise.name, user)
            existing = Exercise.query.filter_by(name=base_name, owner_id=user.id).first()
            if existing:
                exercise = existing
            else:
                exercise = Exercise(
                    name=base_name,
                    muscle_group=exercise.muscle_group,
                    owner_id=user.id,
                    animation_slug=None,
                    youtube_url=None,
                    custom_gif_url=None,
                    media_status='none',
                )
                db.session.add(exercise)
                db.session.flush()
    elif exercise.owner_id != user.id and user.role != 'admin':
        return _deny_manage()

    youtube_raw = data.get('youtube_url') if 'youtube_url' in data else form.get('youtube_url')
    if youtube_raw is not None:
        try:
            exercise.youtube_url = normalize_youtube_url(youtube_raw)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

    upload = request.files.get('gif') or request.files.get('file')
    if upload and upload.filename:
        try:
            exercise.custom_gif_url = save_gif_upload(upload)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

    gif_url_raw = data.get('custom_gif_url') if 'custom_gif_url' in data else form.get('custom_gif_url')
    if gif_url_raw is not None and not upload:
        text = (gif_url_raw or '').strip()
        exercise.custom_gif_url = text or None

    if exercise.youtube_url or exercise.custom_gif_url or exercise.animation_slug:
        if exercise.owner_id is None:
            exercise.media_status = 'approved'
        elif exercise.media_status == 'none':
            exercise.media_status = 'personal'
    else:
        exercise.media_status = 'none'

    queue = str(data.get('queue_promote') or form.get('queue_promote') or '1') not in ('0', 'false', 'False')
    if queue and exercise.owner_id is not None:
        req = _queue_promote_to_common('exercise', exercise, user)
        if req and (exercise.youtube_url or exercise.custom_gif_url):
            try:
                payload = json.loads(req.payload or '{}')
            except (TypeError, ValueError):
                payload = {}
            payload['action'] = 'promote_to_common'
            payload['youtube_url'] = exercise.youtube_url
            payload['custom_gif_url'] = exercise.custom_gif_url
            payload['animation_slug'] = exercise.animation_slug
            payload['media_status'] = 'approved'
            req.payload = json.dumps(payload, ensure_ascii=False)
            req.message = 'Publication média (YouTube / GIF) en banque commune'
            exercise.media_status = 'pending'

    db.session.commit()
    return jsonify(exercise.to_dict())


@api_bp.get('/exercises/media')
@login_required
def lookup_exercise_media():
    """Résout le média : YouTube perso (coach/athlète) prioritaire, sinon commune, sinon map FR."""
    name = (request.args.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name requis'}), 400
    return jsonify(_resolve_exercise_media_payload(name, request.current_user))


def _personal_media_owners(user):
    """Ids dont le média perso peut s’appliquer (soi + coach pour un athlète)."""
    if user is None:
        return []
    owners = []
    role = getattr(user, 'role', None)
    if role in ('coach', 'admin', 'athlete'):
        owners.append(int(user.id))
    if role == 'athlete' and getattr(user, 'coach_id', None):
        owners.append(int(user.coach_id))
    # dédup en préservant l’ordre (perso d’abord, puis coach)
    seen = set()
    ordered = []
    for oid in owners:
        if oid in seen:
            continue
        seen.add(oid)
        ordered.append(oid)
    return ordered


def _find_personal_exercise_for_media(name, public_name, user):
    for oid in _personal_media_owners(user):
        personal = Exercise.query.filter_by(name=name, owner_id=oid).first()
        if personal:
            return personal
        if public_name and public_name != name:
            personal = Exercise.query.filter_by(name=public_name, owner_id=oid).first()
            if personal:
                return personal
        owner = User.query.get(oid)
        if owner is not None:
            suffixed = _ensure_personal_name(public_name or name, owner)
            personal = Exercise.query.filter_by(name=suffixed, owner_id=oid).first()
            if personal:
                return personal
    return None


def _resolve_exercise_media_payload(name, user):
    from app.exercise_animation_map import slug_for_exercise_name
    from app.exercise_media import (
        empty_media_dict, media_dict_from_exercise, media_dict_from_slug,
    )

    name = (name or '').strip()
    if not name:
        return empty_media_dict('')
    public_name = name
    try:
        public_name = _public_name_from_personal(name)
    except Exception:
        public_name = name
    common = Exercise.query.filter_by(name=name, owner_id=None).first()
    if not common and public_name != name:
        common = Exercise.query.filter_by(name=public_name, owner_id=None).first()
    personal = _find_personal_exercise_for_media(name, public_name, user)

    # YouTube / GIF perso prioritaire ; on complète avec l’illustration commune si besoin
    if personal and (personal.animation_slug or personal.youtube_url or personal.custom_gif_url):
        payload = media_dict_from_exercise(personal)
        if common:
            if not payload.get('youtube_url') and common.youtube_url:
                payload['youtube_url'] = common.youtube_url
            if not payload.get('custom_gif_url') and common.custom_gif_url:
                payload['custom_gif_url'] = common.custom_gif_url
            if not payload.get('animation_slug') and common.animation_slug:
                payload['animation_slug'] = common.animation_slug
            payload['has_media'] = bool(
                payload.get('animation_slug') or payload.get('youtube_url') or payload.get('custom_gif_url')
            )
        return payload
    if common and (common.animation_slug or common.youtube_url or common.custom_gif_url):
        return media_dict_from_exercise(common)
    slug = slug_for_exercise_name(name) or slug_for_exercise_name(public_name)
    if slug:
        return media_dict_from_slug(name, slug)
    if common:
        return media_dict_from_exercise(common)
    return empty_media_dict(name)


@api_bp.get('/media/exercises/<path:filename>')
def serve_exercise_media(filename):
    from flask import send_from_directory
    from app.exercise_media import is_safe_media_filename, media_storage_dir

    if not is_safe_media_filename(filename):
        return jsonify({'error': 'Fichier invalide'}), 400
    return send_from_directory(media_storage_dir(), filename)


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
    if request.current_user.role == 'athlete':
        athlete_id = request.current_user.id
    else:
        athlete_id = data.get('athlete_id')
    entry_date = _parse_date(data.get('entry_date'), date.today())
    if not athlete_id:
        return jsonify({'error': 'athlete_id requis'}), 400
    if not _can_manage_athlete(athlete_id):
        return _deny_manage(athlete_id)

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
    if not _can_manage_athlete(entry.athlete_id):
        return _deny_manage(entry.athlete_id)
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
    if not _can_manage_athlete(entry.athlete_id):
        return _deny_manage(entry.athlete_id)
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
    BULK_IMPORT_FIELDS) sont deja renseignes, sans renvoyer les valeurs."""
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
    actuellement None cote serveur."""
    data = request.get_json(silent=True) or {}
    athlete_id = request.current_user.id if request.current_user.role == 'athlete' else data.get('athlete_id')
    if not athlete_id:
        return jsonify({'error': 'athlete_id requis'}), 400
    if not _can_manage_athlete(athlete_id):
        return _deny_manage(athlete_id)
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
    if not _can_manage_athlete(athlete_id):
        return _deny_manage(athlete_id)

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
    if not _can_manage_athlete(entry.athlete_id):
        return _deny_manage(entry.athlete_id)
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
        if e.reps is None or e.load is None:
            continue
        muscle = muscle_by_name.get(e.exercise, 'Autre') or 'Autre'
        tonnage = series_tonnage(e.reps, e.load)
        totals[muscle] = totals.get(muscle, 0) + tonnage
        d = e.entry_date.isoformat()
        trend[d] = trend.get(d, 0) + tonnage

    by_muscle = [{'muscle': m, 'tonnage': round(t, 1)} for m, t in sorted(totals.items(), key=lambda kv: -kv[1])]
    trend_out = [{'date': d, 'tonnage': round(t, 1)} for d, t in sorted(trend.items())]
    return jsonify({'by_muscle': by_muscle, 'trend': trend_out})


@api_bp.get('/stats/journal-trend')
@login_required
def stats_journal_trend():
    """Historique poids / calories / sommeil sur les N derniers jours,
    pour affichage sous forme de graphique."""
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
    if not _can_manage_athlete(entry.athlete_id):
        return _deny_manage(entry.athlete_id)
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
            cur_tonnage += series_tonnage(c_reps, c_load)
            prev_tonnage += series_tonnage(p_reps, p_load)
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
        if e.reps is None or e.load is None:
            continue
        muscle = muscle_by_name.get(e.exercise, 'Autre') or 'Autre'
        tonnage = series_tonnage(e.reps, e.load)
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
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    weeks = max(1, min(int(request.args.get('weeks', 8)), 24))
    muscle_by_name = {e.name: e.muscle_group for e in Exercise.query.all()}

    oldest_start, _ = _week_bounds(weeks - 1)
    _, newest_end = _week_bounds(0)

    journal_all = (JournalEntry.query
                   .filter(JournalEntry.athlete_id == athlete_id,
                           JournalEntry.entry_date >= oldest_start,
                           JournalEntry.entry_date <= newest_end)
                   .all())
    perf_all = (PerformanceEntry.query
                .filter(PerformanceEntry.athlete_id == athlete_id,
                        PerformanceEntry.entry_date >= oldest_start,
                        PerformanceEntry.entry_date <= newest_end)
                .all())

    out = []
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
        sessions = len({e.entry_date for e in perf})
        total_tonnage = round(sum(muscle_totals.values()), 1)
        out.append({
            'offset': offset,
            'label': _week_label(offset),
            'start': start.isoformat(),
            'end': end.isoformat(),
            'sessions': sessions,
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
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    rows = (db.session.query(
                PerformanceEntry.exercise,
                db.func.max(PerformanceEntry.entry_date),
                db.func.count(PerformanceEntry.id))
            .filter(PerformanceEntry.athlete_id == athlete_id)
            .group_by(PerformanceEntry.exercise)
            .order_by(db.func.max(PerformanceEntry.entry_date).desc())
            .limit(80)
            .all())
    return jsonify([
        {'name': name, 'last_date': last.isoformat() if last else None, 'entries': count}
        for name, last, count in rows
    ])


@api_bp.get('/stats/exercises-by-muscle')
@login_required
def stats_exercises_by_muscle():
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    if athlete_id is None:
        return jsonify({'error': 'athlete_id requis'}), 400
    muscle_by_name = {e.name: e.muscle_group for e in Exercise.query.all()}
    entries = PerformanceEntry.query.filter_by(athlete_id=athlete_id).all()
    ex_meta = {}
    for e in entries:
        if not e.exercise:
            continue
        meta = ex_meta.setdefault(e.exercise, {'last': e.entry_date, 'entries': 0, 'tonnage': 0.0})
        meta['entries'] += 1
        if e.entry_date and (meta['last'] is None or e.entry_date > meta['last']):
            meta['last'] = e.entry_date
        if e.load is not None and e.reps is not None:
            meta['tonnage'] += series_tonnage(e.reps, e.load)
    by_muscle = {}
    for name, meta in ex_meta.items():
        muscle = muscle_by_name.get(name, 'Autre') or 'Autre'
        bucket = by_muscle.setdefault(muscle, {'tonnage': 0.0, 'exercises': []})
        bucket['tonnage'] += meta['tonnage']
        bucket['exercises'].append({
            'name': name,
            'last_date': meta['last'].isoformat() if meta['last'] else None,
            'entries': meta['entries'],
        })
    out = []
    for muscle, bucket in by_muscle.items():
        bucket['exercises'].sort(key=lambda e: e['last_date'] or '', reverse=True)
        out.append({
            'muscle': muscle,
            'tonnage': round(bucket['tonnage'], 1),
            'exercises': bucket['exercises'],
        })
    out.sort(key=lambda m: -m['tonnage'])
    return jsonify(out)


@api_bp.get('/stats/exercise-history')
@login_required
def stats_exercise_history():
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    exercise = (request.args.get('exercise') or '').strip()
    if athlete_id is None or not exercise:
        return jsonify({'error': 'athlete_id et exercise requis'}), 400
    days = max(1, min(int(request.args.get('days', 90)), 180))
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
        bucket = by_date.setdefault(d, {
            'loads': [], 'reps': [], 'tonnage': 0.0, 'series': 0,
            'series_rows': [],
        })
        if e.load is not None:
            bucket['loads'].append(e.load)
        if e.reps is not None:
            bucket['reps'].append(e.reps)
        if e.load is not None and e.reps is not None:
            bucket['tonnage'] += series_tonnage(e.reps, e.load)
        bucket['series'] += 1
        bucket['series_rows'].append({
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
            'series': b['series_rows'],
        })
    return jsonify({'exercise': exercise, 'sessions': sessions})


@api_bp.get('/stats/series-breakdown')
@login_required
def stats_series_breakdown():
    athlete_id = _scope_athlete_id(request.args.get('athlete_id'))
    start = _parse_date(request.args.get('start'))
    end = _parse_date(request.args.get('end'))
    if athlete_id is None or not start or not end:
        return jsonify({'error': 'athlete_id, start et end requis'}), 400
    group = (request.args.get('group') or 'week').strip()
    if group not in ('day', 'week', 'month'):
        group = 'week'
    muscle_filter = (request.args.get('muscle') or '').strip() or None
    exercise_filter = (request.args.get('exercise') or '').strip() or None
    muscle_by_name = {e.name: e.muscle_group for e in Exercise.query.all()}

    query = PerformanceEntry.query.filter(
        PerformanceEntry.athlete_id == athlete_id,
        PerformanceEntry.entry_date >= start,
        PerformanceEntry.entry_date <= end,
    )
    if exercise_filter:
        query = query.filter(PerformanceEntry.exercise == exercise_filter)
    entries = query.order_by(PerformanceEntry.entry_date.asc(), PerformanceEntry.series_number.asc()).all()

    buckets = {}
    total_tonnage = 0.0
    total_series = 0
    for e in entries:
        muscle = muscle_by_name.get(e.exercise, 'Autre') or 'Autre'
        if muscle_filter and muscle != muscle_filter:
            continue
        if group == 'day':
            key = e.entry_date.isoformat()
            label = key
        elif group == 'month':
            key = e.entry_date.strftime('%Y-%m')
            label = key
        else:
            ws = _week_start(e.entry_date)
            key = ws.isoformat()
            label = f"Sem. {ws.isoformat()}"
        bucket = buckets.setdefault(key, {
            'key': key, 'label': label, 'tonnage': 0.0, 'series_count': 0, 'series': [],
        })
        ton = series_tonnage(e.reps, e.load)
        bucket['tonnage'] += ton
        bucket['series_count'] += 1
        total_tonnage += ton
        total_series += 1
        bucket['series'].append({
            'date': e.entry_date.isoformat(),
            'exercise': e.exercise,
            'muscle': muscle,
            'series_number': e.series_number,
            'reps': e.reps,
            'load': e.load,
            'notes': e.notes,
            'tonnage': round(ton, 1),
        })

    out_buckets = []
    for key in sorted(buckets.keys()):
        b = buckets[key]
        b['tonnage'] = round(b['tonnage'], 1)
        out_buckets.append(b)

    return jsonify({
        'start': start.isoformat(),
        'end': end.isoformat(),
        'group': group,
        'muscle': muscle_filter,
        'exercise': exercise_filter,
        'buckets': out_buckets,
        'total_tonnage': round(total_tonnage, 1),
        'total_series': total_series,
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
            bucket['tonnage'] += series_tonnage(e.reps, e.load)
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

    # daily activity
    by_date = {}
    for e in perf_all:
        if e.entry_date < cutoff:
            continue
        d = e.entry_date.isoformat()
        bucket = by_date.setdefault(d, {'series': 0, 'tonnage': 0.0, 'exercises': set()})
        bucket['series'] += 1
        if e.load is not None and e.reps is not None:
            bucket['tonnage'] += series_tonnage(e.reps, e.load)
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
            meta['tonnage'] += series_tonnage(e.reps, e.load)
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


@api_bp.get('/foods/equivalents')
@api_bp.post('/foods/equivalents')
@login_required
def list_food_equivalents():
    """Candidats équivalents (kcal calées + macros ±20 %) pour un aliment + grammage.

    GET ?food_id=&quantity=  ou  POST JSON {food_id, quantity}
    """
    from app.food_equivalents import find_food_equivalents, portion_macros

    data = request.get_json(silent=True) or {}
    raw_id = data.get('food_id') if 'food_id' in data else request.args.get('food_id')
    raw_qty = data.get('quantity') if 'quantity' in data else request.args.get('quantity')
    try:
        food_id = int(raw_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'food_id requis'}), 400
    try:
        quantity = float(raw_qty if raw_qty is not None else 100)
    except (TypeError, ValueError):
        quantity = 100.0
    if quantity <= 0:
        quantity = 100.0

    food = Food.query.get(food_id)
    if food is None:
        return jsonify({'error': 'Aliment introuvable'}), 404

    from app.food_equivalents import MIN_G, MAX_G

    target = portion_macros(food, quantity)
    target_kcals = float(target['kcals'] or 0)
    # Préfiltre SQL : seuls les aliments dont 10–500 g peuvent viser les kcal cibles
    owner_scope = _bank_owner_scope_id()
    q = Food.query.filter(_bank_visibility_filter(Food, owner_scope))
    if target_kcals > 0:
        # kcal/100g ∈ [target/MAX_G*100, target/MIN_G*100] (±15 % marge)
        kcal_lo = max(1.0, target_kcals / MAX_G * 100.0 * 0.85)
        kcal_hi = target_kcals / MIN_G * 100.0 * 1.15
        q = q.filter(Food.kcal.isnot(None), Food.kcal >= kcal_lo, Food.kcal <= kcal_hi)
    candidates = q.order_by(Food.name).limit(400).all()
    items = find_food_equivalents(food, quantity, candidates)
    return jsonify({
        'source': {
            'food_id': food.id,
            'food_name': food.name,
            'quantity': quantity,
            **{k: round(v, 1) for k, v in target.items()},
        },
        'equivalents': items,
    })


@api_bp.post('/foods')
@login_required
def create_food():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name or data.get('kcal') is None or data.get('carbs') is None:
        return jsonify({'error': 'name, kcal et carbs requis'}), 400
    user = request.current_user
    as_common = user.role == 'admin' and not bool(data.get('personal'))
    owner_id = None
    if not as_common:
        owner_id = user.id
        name = _ensure_personal_name(name, user)
    if Food.query.filter_by(name=name).first():
        return jsonify({'error': 'Cet aliment existe déjà'}), 409

    food = Food(
        name=name, brand=data.get('brand'), kcal=data['kcal'], proteins=data.get('proteins'),
        lipids=data.get('lipids'), saturated_fats=data.get('saturated_fats'), carbs=data['carbs'],
        simple_sugars=data.get('simple_sugars'), fiber=data.get('fiber'), salt=data.get('salt'),
        owner_id=owner_id,
    )
    db.session.add(food)
    db.session.flush()
    if owner_id is not None:
        _queue_promote_to_common('food', food, user)
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
    with_meals = str(request.args.get('with_meals', '0')).lower() in ('1', 'true', 'yes')
    q = MealPlan.query.filter_by(athlete_id=athlete_id, is_template=False)
    if with_meals:
        from sqlalchemy.orm import selectinload, joinedload
        q = q.options(selectinload(MealPlan.meals).joinedload(MealEntry.food))
    plans = q.order_by(MealPlan.is_active.desc(), MealPlan.created_at.desc()).all()
    return jsonify([p.to_dict(with_meals=with_meals) for p in plans])


@api_bp.get('/meal-plans/<int:plan_id>')
@login_required
def get_meal_plan(plan_id):
    plan = MealPlan.query.get_or_404(plan_id)
    if not _can_manage_athlete(plan.athlete_id):
        return _deny_manage(plan.athlete_id)
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
    has_any = MealPlan.query.filter_by(athlete_id=athlete_id, is_template=False).count() > 0
    plan = MealPlan(
        name=name, athlete_id=athlete_id, coach_id=_coach_id_for_create(athlete_id),
        meal_count=data.get('meal_count', 6), is_active=not has_any, is_template=False,
    )
    db.session.add(plan)
    db.session.flush()
    _sync_meal_plan_to_coach_library(plan)
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
    if not _can_manage_athlete(plan.athlete_id, user):
        return _deny_manage(plan.athlete_id)
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
    _sync_meal_plan_to_coach_library(plan)
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

    _copy_meal_entries_with_equivalents(source.meals, new_plan.id)

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
    db.session.flush()
    if 'equivalents' in data:
        _set_meal_entry_equivalents(entry, data.get('equivalents') or [])
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
    if 'equivalents' in data:
        _set_meal_entry_equivalents(entry, data.get('equivalents') or [])
    db.session.commit()
    return jsonify(entry.to_dict())


@api_bp.put('/meal-entries/<int:entry_id>/equivalents')
@login_required
def replace_meal_entry_equivalents(entry_id):
    entry = MealEntry.query.get_or_404(entry_id)
    plan = MealPlan.query.get_or_404(entry.meal_plan_id)
    if not _can_manage_athlete(plan.athlete_id):
        return _deny_manage()
    data = request.get_json(silent=True) or {}
    items = data.get('equivalents') if isinstance(data, dict) else None
    if items is None and isinstance(data, list):
        items = data
    _set_meal_entry_equivalents(entry, items or [])
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

    is_promote = payload.get('action') == 'promote_to_common'
    if is_promote:
        if target.owner_id is None:
            return jsonify({'error': 'Déjà en banque commune'}), 400
        if target.owner_id != request.current_user.id and request.current_user.role != 'admin':
            return _deny_manage()
        if not payload.get('name'):
            payload = {
                **payload,
                'name': _public_name_from_personal(target.name, request.current_user),
            }
        if not message:
            message = 'Publication en banque commune'
    elif target.owner_id is not None:
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
        'hint': (
            'Publication : le Superadmin pourra diffuser cet item à tous'
            if is_promote
            else 'Tu peux aussi créer ta version perso avec personal=true'
        ),
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
    else:
        target = Food.query.get_or_404(req.target_id)

    if payload.get('action') == 'promote_to_common':
        _, err = _promote_personal_to_common(req.kind, target, payload)
        if err:
            return err
    elif req.kind == 'exercise':
        if payload.get('name'):
            conflict = Exercise.query.filter(
                Exercise.name == payload['name'], Exercise.id != target.id,
            ).first()
            if conflict:
                return jsonify({'error': 'Nom déjà pris'}), 409
            target.name = payload['name']
        if payload.get('muscle_group') in MUSCLE_GROUPS:
            target.muscle_group = payload['muscle_group']
        if 'youtube_url' in payload:
            target.youtube_url = payload.get('youtube_url') or None
        if 'custom_gif_url' in payload:
            target.custom_gif_url = payload.get('custom_gif_url') or None
        if 'animation_slug' in payload and payload.get('animation_slug'):
            target.animation_slug = payload.get('animation_slug')
        if target.animation_slug or target.youtube_url or target.custom_gif_url:
            target.media_status = 'approved'
    else:
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


def _build_athlete_note_summary(payload, questions=None):
    answers = payload if isinstance(payload, dict) else {}
    qs = questions if isinstance(questions, list) else []
    lines = []
    seen = set()
    for q in qs:
        if not q.get('enabled', True):
            continue
        key = q.get('key')
        if not key or key in seen:
            continue
        seen.add(key)
        max_len = 32 if key == 'energy_crash_time' else 500
        value = _clean_note_text(answers.get(key), max_len)
        if not value:
            continue
        label = (q.get('label') or key).strip()
        lines.append(f'{label} : {value}')
    for key, raw in answers.items():
        if key in seen:
            continue
        value = _clean_note_text(raw, 32 if key == 'energy_crash_time' else 500)
        if value:
            lines.append(f'{key} : {value}')
    return '\n'.join(lines) if lines else None


def _extract_bilan_note_answers(data, questions):
    answers = {}
    enabled = [q for q in (questions or []) if q.get('enabled', True) and q.get('key')]
    source = data.get('answers') if isinstance(data.get('answers'), dict) else data
    for q in enabled:
        key = q['key']
        max_len = 32 if key == 'energy_crash_time' else 500
        answers[key] = _clean_note_text(source.get(key), max_len)
    return answers



def _journal_streak(athlete_id, today):
    """Jours consecutifs avec journal. Si aujourd'hui vide, part d'hier."""
    dates = {
        d for (d,) in db.session.query(JournalEntry.entry_date).filter(
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
    logs = (
        db.session.query(
            PerformanceEntry.entry_date,
            PerformanceEntry.program_session_id,
        )
        .filter(
            PerformanceEntry.athlete_id == athlete_id,
            PerformanceEntry.entry_date >= oldest,
        )
        .all()
    )
    logged_dates = {e[0] for e in logs}
    logged_by_session_date = {
        (e[1], e[0])
        for e in logs if e[1] is not None
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
    has_questions = bool(user.get_bilan_note_questions(enabled_only=True))
    return {
        'bilan_weekday': weekday,
        'bilan_day_label': DAY_NAMES_FR[weekday] if weekday is not None else None,
        'is_bilan_day': weekday is not None and today.weekday() == weekday,
        'is_bilan_eve': j_minus_1 is not None and today.weekday() == j_minus_1,
        'can_write_note': weekday is not None and user.coach_id is not None and has_questions,
    }


def _get_or_create_marking(athlete_id, week_start, done=False):
    marking = MobileWeeklyBilanMarking.query.filter_by(athlete_id=athlete_id, week_start=week_start).first()
    if marking:
        return marking
    marking = MobileWeeklyBilanMarking(athlete_id=athlete_id, week_start=week_start, done=done)
    db.session.add(marking)
    return marking


# ------------------------------------------------------------- METABOLISM ---

def _latest_journal_weight(athlete_id: int):
    row = (
        JournalEntry.query
        .filter(JournalEntry.athlete_id == athlete_id, JournalEntry.weight.isnot(None))
        .order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc())
        .first()
    )
    return float(row.weight) if row and row.weight is not None else None


def _parse_optional_date(raw):
    if raw is None or raw == '':
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    return datetime.strptime(str(raw)[:10], '%Y-%m-%d').date()


def _parse_optional_float(raw, *, lo=None, hi=None):
    if raw is None or raw == '':
        return None
    v = float(raw)
    if lo is not None and v < lo:
        raise ValueError(f'valeur < {lo}')
    if hi is not None and v > hi:
        raise ValueError(f'valeur > {hi}')
    return v


def _parse_optional_int(raw, *, lo=None, hi=None):
    if raw is None or raw == '':
        return None
    v = int(round(float(raw)))
    if lo is not None and v < lo:
        raise ValueError(f'valeur < {lo}')
    if hi is not None and v > hi:
        raise ValueError(f'valeur > {hi}')
    return v


@api_bp.get('/athlete/metabolism')
@login_required
def get_athlete_metabolism():
    from app.metabolism import ACTIVITY_LABELS, GOAL_LABELS, TENDENCY_LABELS, compute_metabolism, energy_balance_report
    user = request.current_user
    if user.role != 'athlete':
        return jsonify({'error': 'Réservé à l\'athlète'}), 403
    if not _has_independent(user):
        return jsonify({'error': 'Module Indépendant requis', 'code': 'INDEPENDENT_REQUIRED'}), 403

    journal_w = _latest_journal_weight(user.id)
    weight = journal_w if journal_w is not None else user.profile_weight_kg
    meta = compute_metabolism(user, weight_kg=float(weight) if weight is not None else None)
    meta['weight_source'] = (
        'journal' if journal_w is not None
        else 'profile' if user.profile_weight_kg is not None
        else None
    )

    balance = None
    start = user.energy_balance_start_date
    if start and meta.get('target_kcal'):
        entries = (
            JournalEntry.query
            .filter(
                JournalEntry.athlete_id == user.id,
                JournalEntry.entry_date >= start,
                JournalEntry.kcals.isnot(None),
            )
            .order_by(JournalEntry.entry_date.asc())
            .all()
        )
        balance = energy_balance_report(entries, target_kcal=meta['target_kcal'], start=start)

    return jsonify({
        'metabolism': meta,
        'balance': balance,
        'options': {
            'activity_levels': [{'value': k, 'label': v} for k, v in ACTIVITY_LABELS.items()],
            'tendencies': [{'value': k, 'label': v} for k, v in TENDENCY_LABELS.items()],
            'goals': [{'value': k, 'label': v} for k, v in GOAL_LABELS.items()],
        },
    })


@api_bp.put('/athlete/metabolism')
@login_required
def put_athlete_metabolism():
    from app.metabolism import ACTIVITY_FACTORS, GOAL_LABELS, TENDENCY_FACTORS, clamp_goal_delta, compute_metabolism
    user = request.current_user
    if user.role != 'athlete':
        return jsonify({'error': 'Réservé à l\'athlète'}), 403
    if not _has_independent(user):
        return jsonify({'error': 'Module Indépendant requis', 'code': 'INDEPENDENT_REQUIRED'}), 403

    data = request.get_json(silent=True) or {}
    try:
        if 'sex' in data:
            sex = (data.get('sex') or '').strip().lower() or None
            if sex in ('male', 'man', 'homme'):
                sex = 'm'
            elif sex in ('female', 'woman', 'femme'):
                sex = 'f'
            if sex not in (None, 'm', 'f'):
                return jsonify({'error': 'sex invalide (m|f)'}), 400
            user.sex = sex
        if 'height_cm' in data:
            user.height_cm = _parse_optional_float(data.get('height_cm'), lo=100, hi=250)
        if 'birth_date' in data:
            user.birth_date = _parse_optional_date(data.get('birth_date'))
        if 'profile_weight_kg' in data:
            user.profile_weight_kg = _parse_optional_float(data.get('profile_weight_kg'), lo=30, hi=300)
        if 'body_fat_pct' in data:
            user.body_fat_pct = _parse_optional_float(data.get('body_fat_pct'), lo=3, hi=60)
        if 'activity_level' in data:
            act = data.get('activity_level') or None
            if act and act not in ACTIVITY_FACTORS:
                return jsonify({'error': 'activity_level invalide'}), 400
            user.activity_level = act
        if 'metabolic_tendency' in data:
            ten = data.get('metabolic_tendency') or None
            if ten and ten not in TENDENCY_FACTORS:
                return jsonify({'error': 'metabolic_tendency invalide'}), 400
            user.metabolic_tendency = ten
        if 'bmr_override' in data:
            user.bmr_override = _parse_optional_int(data.get('bmr_override'), lo=800, hi=5000)
        if 'tdee_override' in data:
            user.tdee_override = _parse_optional_int(data.get('tdee_override'), lo=1000, hi=8000)
        if 'energy_goal' in data:
            goal = data.get('energy_goal') or None
            if goal and goal not in GOAL_LABELS:
                return jsonify({'error': 'energy_goal invalide'}), 400
            user.energy_goal = goal
        if 'energy_goal_delta' in data:
            raw = data.get('energy_goal_delta')
            user.energy_goal_delta = clamp_goal_delta(raw) if raw not in (None, '') else None
        if 'energy_balance_start_date' in data:
            user.energy_balance_start_date = _parse_optional_date(data.get('energy_balance_start_date'))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    db.session.commit()
    journal_w = _latest_journal_weight(user.id)
    weight = journal_w if journal_w is not None else user.profile_weight_kg
    meta = compute_metabolism(user, weight_kg=float(weight) if weight is not None else None)
    return jsonify({'metabolism': meta, 'user': user.to_dict()})


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
        'athlete_note': marking.note_dict() if marking else None,
        'metrics': metrics,
        'objectives': [o.to_dict() for o in objectives],
        'muscles': muscle_rows,
        'attention': attention,
    }
    return jsonify([entry])


@api_bp.post('/athlete/bilan-hebdo/note')
@login_required
def athlete_save_bilan_note():
    """Athlète coached : rédige son mot de bilan pour la semaine en cours."""
    user = request.current_user
    if user.role != 'athlete':
        return jsonify({'error': 'Réservé à l\'athlète'}), 403
    if not user.coach_id:
        return jsonify({'error': 'Aucun coach associé'}), 400
    ctx = _athlete_bilan_context(user)
    if user.bilan_weekday is None:
        return jsonify({'error': "Ton coach n'a pas encore choisi ton jour de bilan"}), 400

    data = request.get_json(silent=True) or {}
    week_start = _parse_date(data.get('week_start')) or _week_start(date.today())
    questions = user.get_bilan_note_questions(enabled_only=True)
    if not questions:
        return jsonify({'error': "Ton coach n'a pas encore configuré les questions de bilan"}), 400
    payload = _extract_bilan_note_answers(data, questions)
    summary = _build_athlete_note_summary(payload, questions)
    if not summary:
        return jsonify({'error': 'Écris au moins un élément de bilan'}), 400

    marking = _get_or_create_marking(user.id, week_start, done=False)
    marking.athlete_note = summary
    marking.athlete_note_json = json.dumps(payload, ensure_ascii=False)
    marking.athlete_note_updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(marking.to_dict())


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
        # Conserve le mot athlète : on ne fait que décocher le bilan.
        marking.done = False
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
    ('energy', 'Énergie (/10)'),
    ('stress', 'Stress (/10)'),
    ('tonnage', 'Tonnage (kg)'),
    ('sessions', 'Séances loggées'),
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
    # Attention : 8 semaines suffisent (évite 180j × équipe entière).
    attention_days = min(int(request.args.get('attention_days', 56)), 120)
    attention_cutoff = today - timedelta(days=attention_days)

    # Easy Bilan = uniquement les athlètes de l'équipe du compte connecté (coach ou admin).
    athletes_q = _coach_team_query(request.current_user.id).order_by(User.username)
    # Pagination optionnelle pour grosses équipes
    try:
        limit = int(request.args.get('limit') or 0)
    except (TypeError, ValueError):
        limit = 0
    try:
        offset = int(request.args.get('offset') or 0)
    except (TypeError, ValueError):
        offset = 0
    athlete_filter = request.args.get('athlete_id')
    if athlete_filter:
        try:
            aid = int(athlete_filter)
        except (TypeError, ValueError):
            return jsonify({'error': 'athlete_id invalide'}), 400
        if not _coach_owns_athlete(request.current_user, aid):
            return jsonify({'error': 'Athlète non autorisé'}), 403
        athletes = athletes_q.filter(User.id == aid).all()
    else:
        if limit > 0:
            athletes = athletes_q.offset(max(offset, 0)).limit(min(limit, 50)).all()
        else:
            athletes = athletes_q.limit(50).all()
    if not athletes:
        return jsonify([])
    athlete_ids = [a.id for a in athletes]

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

    # Ne charge que les exercices réellement présents dans les perfs (pas toute la banque).
    exercise_names = {p.exercise for p in perf_rows if p.exercise}
    muscle_by_name = {}
    if exercise_names:
        for e in Exercise.query.filter(Exercise.name.in_(list(exercise_names))).all():
            muscle_by_name[e.name] = e.muscle_group

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


def _coach_owns_athlete(coach, athlete_id):
    """Jour de bilan / actions bilan : uniquement les athlètes de CETTE équipe."""
    athlete = User.query.get(athlete_id)
    return bool(athlete and athlete.role == 'athlete' and athlete.coach_id == coach.id)


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
        'questions': athlete.get_bilan_note_questions(),
    })


@api_bp.put('/coach/athletes/<int:athlete_id>/bilan-settings')
@coach_required
def put_athlete_bilan_settings(athlete_id):
    if not _coach_owns_athlete(request.current_user, athlete_id):
        return jsonify({'error': 'Athlète non autorisé'}), 403
    athlete = User.query.get_or_404(athlete_id)
    if athlete.role != 'athlete':
        return jsonify({'error': 'Utilisateur non athlète'}), 400
    data = request.get_json(silent=True) or {}
    touched = False
    weekday = int(athlete.bilan_weekday) if athlete.bilan_weekday is not None else None

    if 'bilan_weekday' in data and data.get('bilan_weekday') is not None:
        try:
            weekday = int(data.get('bilan_weekday'))
        except (TypeError, ValueError):
            return jsonify({'error': 'bilan_weekday requis (0=lundi … 6=dimanche)'}), 400
        if weekday < 0 or weekday > 6:
            return jsonify({'error': 'bilan_weekday doit être entre 0 et 6'}), 400
        athlete.bilan_weekday = weekday
        touched = True

    if 'questions' in data:
        try:
            if data.get('questions') is None:
                athlete.set_bilan_note_questions(None)
            else:
                athlete.set_bilan_note_questions(data.get('questions'))
        except ValueError as err:
            return jsonify({'error': str(err)}), 400
        touched = True

    if not touched:
        return jsonify({'error': 'bilan_weekday ou questions requis'}), 400

    db.session.commit()
    return jsonify({
        'athlete_id': athlete.id,
        'bilan_weekday': weekday,
        'bilan_day_label': DAY_NAMES_FR[weekday] if weekday is not None else None,
        'required': True,
        'questions': athlete.get_bilan_note_questions(),
        'athlete': athlete.to_dict(),
    })


_PRIVATE_NOTE_MAX = 8000


@api_bp.get('/coach/athletes/<int:athlete_id>/private-note')
@coach_required
def get_athlete_private_note(athlete_id):
    user = request.current_user
    if not _can_manage_athlete(athlete_id, user):
        return jsonify({'error': 'Athlète non autorisé'}), 403
    row = CoachAthletePrivateNote.query.filter_by(
        coach_id=user.id, athlete_id=int(athlete_id),
    ).first()
    if not row:
        return jsonify({'athlete_id': int(athlete_id), 'note': '', 'updated_at': None})
    return jsonify(row.to_dict())


@api_bp.put('/coach/athletes/<int:athlete_id>/private-note')
@coach_required
def put_athlete_private_note(athlete_id):
    user = request.current_user
    if not _can_manage_athlete(athlete_id, user):
        return jsonify({'error': 'Athlète non autorisé'}), 403
    athlete = User.query.get_or_404(athlete_id)
    if athlete.role != 'athlete':
        return jsonify({'error': 'Utilisateur non athlète'}), 400
    data = request.get_json(silent=True) or {}
    if 'note' not in data:
        return jsonify({'error': 'note requis'}), 400
    body = str(data.get('note') or '')
    if len(body) > _PRIVATE_NOTE_MAX:
        return jsonify({'error': f'Note trop longue (max {_PRIVATE_NOTE_MAX} caractères)'}), 400
    row = CoachAthletePrivateNote.query.filter_by(
        coach_id=user.id, athlete_id=int(athlete_id),
    ).first()
    if row is None:
        row = CoachAthletePrivateNote(coach_id=user.id, athlete_id=int(athlete_id), body=body)
        db.session.add(row)
    else:
        row.body = body
    row.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(row.to_dict())


@api_bp.put('/coach/bilan-settings')
@coach_required
def put_bilan_settings_compat():
    data = request.get_json(silent=True) or {}
    athlete_id = data.get('athlete_id')
    if not athlete_id:
        return jsonify({'error': 'athlete_id requis — le jour de bilan se choisit par athlète'}), 400
    return put_athlete_bilan_settings(int(athlete_id))

@api_bp.post('/coach/bilan-hebdo/mark')
@coach_required
def mark_weekly_bilan():
    data = request.get_json(silent=True) or {}
    athlete_id = data.get('athlete_id')
    week_start = _parse_date(data.get('week_start'), _week_start(date.today()))
    if not athlete_id:
        return jsonify({'error': 'athlete_id requis'}), 400
    if not _coach_owns_athlete(request.current_user, int(athlete_id)):
        return _deny_manage(athlete_id, reason='bilan_mark_denied')

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
    if not athlete_id:
        return jsonify({'error': 'athlete_id requis'}), 400
    if not _coach_owns_athlete(request.current_user, int(athlete_id)):
        return _deny_manage(athlete_id, reason='bilan_unmark_denied')
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


# ---------------------------------------------------- COACH PROFILE / SEARCH -

CONTACT_CHANNELS = {'phone', 'whatsapp', 'email', 'instagram', 'other'}


@api_bp.get('/coach/profile')
@coach_required
def get_coach_profile():
    user = request.current_user
    data = user.coach_profile_dict(reveal_contact=True)
    data['user'] = user.to_dict()
    return jsonify(data)


@api_bp.get('/coach/youtube/status')
@coach_required
def coach_youtube_status():
    from app.youtube_oauth import youtube_oauth_configured
    user = request.current_user
    return jsonify({
        'configured': youtube_oauth_configured(),
        'connected': bool(user.youtube_refresh_token),
        'channel_id': user.youtube_channel_id,
        'channel_title': user.youtube_channel_title,
        'connected_at': user.youtube_connected_at.isoformat() if user.youtube_connected_at else None,
        'note': (
            'Les vidéos privées restent visibles seulement pour ton compte Google. '
            'Pour tes athlètes, utilise des vidéos non répertoriées ou publiques.'
        ),
    })


@api_bp.get('/coach/youtube/auth-url')
@coach_required
def coach_youtube_auth_url():
    from app.youtube_oauth import build_authorize_url, youtube_oauth_configured
    if not youtube_oauth_configured():
        return jsonify({
            'error': 'YouTube non configuré côté serveur (GOOGLE_OAUTH_CLIENT_ID / SECRET)',
            'code': 'YOUTUBE_OAUTH_MISSING',
        }), 503
    try:
        url = build_authorize_url(request.current_user.id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 503
    return jsonify({'url': url})


@api_bp.get('/coach/youtube/callback')
def coach_youtube_callback():
    """Redirect Google OAuth → stocke le refresh token → deep link app."""
    from app.youtube_oauth import (
        exchange_code_for_tokens, fetch_channel_info, parse_oauth_state,
    )
    err = request.args.get('error')
    if err:
        return (
            '<!doctype html><html><body style="font-family:sans-serif;padding:24px">'
            f'<h2>Connexion YouTube annulée</h2><p>{err}</p>'
            '<p><a href="farmness://youtube-connected?ok=0">Retour à l’app</a></p>'
            '</body></html>'
        ), 400

    code = request.args.get('code')
    state = request.args.get('state')
    if not code or not state:
        return jsonify({'error': 'code/state manquants'}), 400
    try:
        user_id = parse_oauth_state(state)
    except Exception:
        return jsonify({'error': 'state invalide ou expiré'}), 400

    user = User.query.get(user_id)
    if not user or user.role not in ('coach', 'admin'):
        return jsonify({'error': 'Utilisateur invalide'}), 400

    try:
        tokens = exchange_code_for_tokens(code)
        access = tokens.get('access_token')
        refresh = tokens.get('refresh_token') or user.youtube_refresh_token
        if not refresh:
            return (
                '<!doctype html><html><body style="font-family:sans-serif;padding:24px">'
                '<h2>Pas de refresh token</h2>'
                '<p>Réessaie en révoquant l’accès Farmness dans ton compte Google, puis reconnecte.</p>'
                '<p><a href="farmness://youtube-connected?ok=0">Retour à l’app</a></p>'
                '</body></html>'
            ), 400
        info = fetch_channel_info(access)
        items = info.get('items') or []
        ch = items[0] if items else {}
        user.youtube_refresh_token = refresh
        user.youtube_channel_id = ch.get('id')
        user.youtube_channel_title = ((ch.get('snippet') or {}).get('title'))
        user.youtube_connected_at = datetime.utcnow()
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return (
            '<!doctype html><html><body style="font-family:sans-serif;padding:24px">'
            f'<h2>Erreur YouTube</h2><p>{exc}</p>'
            '<p><a href="farmness://youtube-connected?ok=0">Retour à l’app</a></p>'
            '</body></html>'
        ), 502

    return (
        '<!doctype html><html><body style="font-family:sans-serif;padding:24px;text-align:center">'
        '<h2>YouTube connecté</h2>'
        '<p>Tu peux fermer cette page et revenir dans Farmness.</p>'
        '<script>location.href="farmness://youtube-connected?ok=1";</script>'
        '<p><a href="farmness://youtube-connected?ok=1">Ouvrir l’app</a></p>'
        '</body></html>'
    )


@api_bp.delete('/coach/youtube')
@coach_required
def coach_youtube_disconnect():
    user = request.current_user
    user.youtube_refresh_token = None
    user.youtube_channel_id = None
    user.youtube_channel_title = None
    user.youtube_connected_at = None
    db.session.commit()
    return jsonify({'ok': True})


@api_bp.get('/coach/youtube/videos')
@coach_required
def coach_youtube_videos():
    from app.youtube_oauth import enrich_privacy, list_my_videos, refresh_access_token, youtube_oauth_configured
    user = request.current_user
    if not youtube_oauth_configured():
        return jsonify({'error': 'YouTube non configuré', 'code': 'YOUTUBE_OAUTH_MISSING'}), 503
    if not user.youtube_refresh_token:
        return jsonify({'error': 'YouTube non connecté', 'code': 'YOUTUBE_NOT_CONNECTED'}), 401
    try:
        tok = refresh_access_token(user.youtube_refresh_token)
        access = tok.get('access_token')
        if tok.get('refresh_token'):
            user.youtube_refresh_token = tok['refresh_token']
            db.session.commit()
        page = request.args.get('page_token') or None
        raw = list_my_videos(access, page_token=page, max_results=int(request.args.get('limit') or 24))
        videos = enrich_privacy(access, raw.get('videos') or [])
        if raw.get('channel_title') and not user.youtube_channel_title:
            user.youtube_channel_title = raw['channel_title']
            db.session.commit()
        return jsonify({
            'videos': videos,
            'next_page_token': raw.get('next_page_token'),
            'channel_title': user.youtube_channel_title or raw.get('channel_title'),
            'note': (
                'Privé = toi seul. Non répertorié = OK pour tes athlètes avec le lien. '
                'Public = visible partout.'
            ),
        })
    except Exception as exc:
        return jsonify({'error': f'YouTube API : {exc}'}), 502


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
    city = (request.args.get('city') or '').strip()
    q = User.query.filter(User.role == 'coach')
    if city:
        like = f'%{city}%'
        q = q.filter(User.city.ilike(like))
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


@api_bp.delete('/athlete/coach')
@login_required
def athlete_leave_coach():
    """L'athlète se détache de son coach (compte et données gardés)."""
    user = request.current_user
    if user.role != 'athlete':
        return jsonify({'error': "Réservé à l'athlète"}), 403
    if not user.coach_id:
        return jsonify({'error': "Tu n'as pas de coach"}), 400
    coach_id = user.coach_id
    _snapshot_athlete_content_to_coach_library(coach_id, user)
    _link_athlete_to_coach(user, None)
    CoachingInvitation.query.filter_by(
        coach_id=coach_id, athlete_id=user.id, status='pending',
    ).update({'status': 'refused'}, synchronize_session=False)
    db.session.commit()
    return jsonify({'ok': True, 'user': user.to_dict()})


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
    """Demandes athlète→coach : uniquement celles adressées à ce compte."""
    user = request.current_user
    rows = (
        CoachingInvitation.query
        .filter_by(coach_id=user.id, status='pending', direction='athlete_to_coach')
        .order_by(CoachingInvitation.created_at.desc())
        .all()
    )
    return jsonify([i.to_dict() for i in rows])


@api_bp.post('/coach/athlete-requests/<int:invitation_id>/accept')
@coach_required
def accept_athlete_request(invitation_id):
    user = request.current_user
    inv = CoachingInvitation.query.get_or_404(invitation_id)
    if inv.status != 'pending' or (inv.direction or '') != 'athlete_to_coach':
        return jsonify({'error': 'Demande invalide'}), 400
    if inv.coach_id != user.id:
        return jsonify({'error': 'Non autorisé'}), 403
    coach = User.query.get(inv.coach_id)
    athlete = User.query.get(inv.athlete_id)
    if not coach or not athlete or athlete.role != 'athlete':
        return jsonify({'error': 'Utilisateur introuvable'}), 404
    if athlete.coach_id:
        return jsonify({'error': 'Cet athlète a déjà un coach'}), 409
    limit = coach.athlete_limit()
    if limit is not None and _coach_quota_count(coach.id) >= limit:
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
    if inv.coach_id != user.id:
        return jsonify({'error': 'Non autorisé'}), 403
    inv.status = 'refused'
    db.session.commit()
    return jsonify(inv.to_dict())


# ---------------------------------------------------- ADMIN SECURITY EVENTS -

@api_bp.get('/admin/security-events')
@admin_required
def list_security_events():
    """Journal des tentatives suspectes (superadmin)."""
    q = SecurityEvent.query.order_by(SecurityEvent.created_at.desc())
    severity = (request.args.get('severity') or '').strip().lower()
    event_type = (request.args.get('type') or request.args.get('event_type') or '').strip()
    reviewed = request.args.get('reviewed')
    if severity:
        q = q.filter(SecurityEvent.severity == severity)
    if event_type:
        q = q.filter(SecurityEvent.event_type == event_type)
    if reviewed is not None and reviewed != '':
        want = str(reviewed).lower() in ('1', 'true', 'yes')
        q = q.filter(SecurityEvent.reviewed.is_(want))
    try:
        limit = min(max(int(request.args.get('limit', 100)), 1), 500)
    except (TypeError, ValueError):
        limit = 100
    rows = q.limit(limit).all()
    return jsonify([r.to_dict() for r in rows])


@api_bp.post('/admin/security-events/<int:event_id>/review')
@admin_required
def review_security_event(event_id):
    row = SecurityEvent.query.get_or_404(event_id)
    data = request.get_json(silent=True) or {}
    row.reviewed = bool(data.get('reviewed', True))
    row.reviewed_at = datetime.utcnow() if row.reviewed else None
    row.reviewed_by_id = request.current_user.id if row.reviewed else None
    db.session.commit()
    return jsonify(row.to_dict())
