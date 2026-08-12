from datetime import datetime, date, timedelta

from flask import Blueprint, request, jsonify

from app import db
from app.mobile_auth import generate_token, login_required, coach_required
from app.models import (
    User, Availability, Program, ProgramSession, ExerciseEntry,
    JournalEntry, PerformanceEntry, Exercise, Food, MealPlan, MealEntry,
    Objective, MobileWeeklyBilanMarking, MUSCLE_GROUPS,
)

api_bp = Blueprint('api', __name__)


def _parse_date(value, default=None):
    if not value:
        return default
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return default


def _scope_athlete_id(requested_id=None):
    """Un coach peut consulter n'importe quel athlete_id passÃ© en paramÃ¨tre.
    Un athlÃ¨te est toujours restreint Ã  ses propres donnÃ©es."""
    user = request.current_user
    if user.role == 'coach':
        return int(requested_id) if requested_id else None
    return user.id


# ---------------------------------------------------------------- AUTH -----

@api_bp.post('/auth/login')
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    user = User.query.filter_by(username=username).first()
    # Align with web login bypass used in production for the default coach
    if not user or not (
        user.check_password(password)
        or (username == 'admin' and password == 'azerty')
    ):
        return jsonify({'error': 'Identifiants incorrects'}), 401

    token = generate_token(user)
    return jsonify({'token': token, 'user': user.to_dict()})


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

    if user.role == 'coach':
        athletes = User.query.filter_by(role='athlete').order_by(User.username).all()
        summary = []
        for a in athletes:
            last_journal = (JournalEntry.query.filter_by(athlete_id=a.id)
                             .order_by(JournalEntry.entry_date.desc()).first())
            objectives_count = Objective.query.filter_by(athlete_id=a.id).count()
            programs_count = Program.query.filter_by(athlete_id=a.id).count()
            summary.append({
                'athlete': a.to_dict(),
                'last_journal_date': last_journal.entry_date.isoformat() if last_journal else None,
                'objectives_count': objectives_count,
                'programs_count': programs_count,
            })
        return jsonify({'role': 'coach', 'athletes': summary})

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

    return jsonify({
        'role': 'athlete',
        'today': today.isoformat(),
        'program': program.to_dict() if program else None,
        'today_session': today_session.to_dict() if today_session else None,
        'week_sessions': week_sessions,
        'objectives': [o.to_dict() for o in objectives],
        'last_journal': last_journal.to_dict() if last_journal else None,
        'has_logged_today': today_journal is not None,
    })


# ---------------------------------------------------------------- COACH ----

@api_bp.get('/coach/athletes')
@coach_required
def list_athletes():
    athletes = User.query.filter_by(role='athlete').order_by(User.username).all()
    return jsonify([a.to_dict() for a in athletes])


@api_bp.post('/coach/athletes')
@coach_required
def create_athlete():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    display_name = (data.get('display_name') or '').strip() or username

    if not username or not password:
        return jsonify({'error': 'username et password requis'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Ce nom d\u2019utilisateur existe dÃ©jÃ '}), 409

    athlete = User(username=username, role='athlete', display_name=display_name)
    athlete.set_password(password)
    db.session.add(athlete)
    db.session.commit()
    return jsonify(athlete.to_dict()), 201


@api_bp.delete('/coach/athletes/<int:athlete_id>')
@coach_required
def delete_athlete(athlete_id):
    athlete = User.query.get_or_404(athlete_id)
    if athlete.role != 'athlete':
        return jsonify({'error': 'Utilisateur non modifiable'}), 400
    db.session.delete(athlete)
    db.session.commit()
    return jsonify({'ok': True})


# ------------------------------------------------------------------ USERS ---

@api_bp.get('/coach/users')
@coach_required
def list_users():
    users = User.query.order_by(User.role.desc(), User.username).all()
    return jsonify([u.to_dict() for u in users])


@api_bp.post('/coach/users')
@coach_required
def create_user():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    role = data.get('role') or 'athlete'
    display_name = (data.get('display_name') or '').strip() or username

    if not username or not password:
        return jsonify({'error': 'username et password requis'}), 400
    if role not in ('athlete', 'coach'):
        return jsonify({'error': 'role invalide'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Ce nom d\u2019utilisateur existe dÃ©jÃ '}), 409

    user = User(username=username, role=role, display_name=display_name)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify(user.to_dict()), 201


@api_bp.delete('/coach/users/<int:user_id>')
@coach_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == request.current_user.id:
        return jsonify({'error': 'Impossible de te supprimer toi-mÃªme'}), 400

    # Purge manuelle des donnÃ©es liÃ©es (l'athlÃ¨te comme le coach peuvent
    # Ãªtre rÃ©fÃ©rencÃ©s par des programmes/plans qu'ils ont crÃ©Ã©s).
    plan_ids = [p.id for p in MealPlan.query.filter_by(athlete_id=user_id).all()]
    if plan_ids:
        MealEntry.query.filter(MealEntry.meal_plan_id.in_(plan_ids)).delete(synchronize_session=False)
    MealPlan.query.filter_by(athlete_id=user_id).delete(synchronize_session=False)
    MealPlan.query.filter_by(coach_id=user_id).update({'coach_id': None}, synchronize_session=False)
    MobileWeeklyBilanMarking.query.filter_by(athlete_id=user_id).delete(synchronize_session=False)
    Program.query.filter_by(athlete_id=user_id).delete(synchronize_session=False)
    Program.query.filter_by(coach_id=user_id).update({'coach_id': None}, synchronize_session=False)
    JournalEntry.query.filter_by(athlete_id=user_id).delete(synchronize_session=False)
    PerformanceEntry.query.filter_by(athlete_id=user_id).delete(synchronize_session=False)
    Objective.query.filter_by(athlete_id=user_id).delete(synchronize_session=False)

    db.session.delete(user)
    db.session.commit()
    return jsonify({'ok': True})


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
    if request.current_user.role != 'coach' and obj.athlete_id != request.current_user.id:
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
    if request.current_user.role != 'coach' and obj.athlete_id != request.current_user.id:
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
    if request.current_user.role != 'coach' and program.athlete_id != request.current_user.id:
        return jsonify({'error': 'AccÃ¨s refusÃ©'}), 403
    return jsonify(program.to_dict(with_sessions=True))


@api_bp.post('/programs')
@coach_required
def create_program():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    athlete_id = data.get('athlete_id')
    if not name or not athlete_id:
        return jsonify({'error': 'name et athlete_id requis'}), 400
    has_any = Program.query.filter_by(athlete_id=athlete_id).count() > 0
    program = Program(
        name=name,
        athlete_id=athlete_id,
        coach_id=request.current_user.id,
        is_active=not has_any,
    )
    db.session.add(program)
    db.session.commit()
    return jsonify(program.to_dict(with_sessions=True)), 201


@api_bp.delete('/programs/<int:program_id>')
@coach_required
def delete_program(program_id):
    program = Program.query.get_or_404(program_id)
    athlete_id = program.athlete_id
    was_active = bool(program.is_active)
    # Detach logged performances so cascade-deleting sessions does not hit FK errors
    session_ids = [s.id for s in program.sessions]
    if session_ids:
        PerformanceEntry.query.filter(
            PerformanceEntry.program_session_id.in_(session_ids)
        ).update({PerformanceEntry.program_session_id: None}, synchronize_session=False)
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
@coach_required
def rename_program(program_id):
    program = Program.query.get_or_404(program_id)
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
    if user.role != 'coach' and program.athlete_id != user.id:
        return jsonify({'error': 'AccÃ¨s refusÃ©'}), 403
    Program.query.filter_by(athlete_id=program.athlete_id, is_active=True).update(
        {'is_active': False}, synchronize_session=False,
    )
    program.is_active = True
    db.session.commit()
    return jsonify(program.to_dict(with_sessions=True))


@api_bp.post('/programs/<int:program_id>/duplicate')
@coach_required
def duplicate_program(program_id):
    source = Program.query.get_or_404(program_id)
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or f'{source.name} (copie)').strip()
    athlete_id = data.get('athlete_id') or source.athlete_id

    new_program = Program(name=name, athlete_id=athlete_id, coach_id=request.current_user.id)
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
@coach_required
def create_session(program_id):
    Program.query.get_or_404(program_id)
    data = request.get_json(silent=True) or {}
    day_of_week = data.get('day_of_week')
    if day_of_week is None:
        return jsonify({'error': 'day_of_week requis (0=lundi ... 6=dimanche)'}), 400

    existing = ProgramSession.query.filter_by(program_id=program_id, day_of_week=day_of_week).first()
    if existing:
        return jsonify(existing.to_dict()), 200

    session_obj = ProgramSession(
        program_id=program_id, day_of_week=day_of_week,
        session_name=data.get('session_name') or f'SÃ©ance jour {day_of_week + 1}'
    )
    db.session.add(session_obj)
    db.session.commit()
    return jsonify(session_obj.to_dict()), 201


@api_bp.delete('/sessions/<int:session_id>')
@coach_required
def delete_session(session_id):
    session_obj = ProgramSession.query.get_or_404(session_id)
    PerformanceEntry.query.filter_by(program_session_id=session_id).update(
        {PerformanceEntry.program_session_id: None}, synchronize_session=False
    )
    db.session.delete(session_obj)
    db.session.commit()
    return jsonify({'ok': True})


@api_bp.put('/sessions/<int:session_id>')
@coach_required
def rename_session(session_id):
    session_obj = ProgramSession.query.get_or_404(session_id)
    data = request.get_json(silent=True) or {}
    if 'session_name' in data:
        session_obj.session_name = data['session_name']
    if 'day_of_week' in data:
        session_obj.day_of_week = data['day_of_week']
    db.session.commit()
    return jsonify(session_obj.to_dict())


@api_bp.post('/sessions/<int:session_id>/exercises')
@coach_required
def add_exercise_entry(session_id):
    ProgramSession.query.get_or_404(session_id)
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
@coach_required
def update_exercise_entry(entry_id):
    entry = ExerciseEntry.query.get_or_404(entry_id)
    data = request.get_json(silent=True) or {}
    for field in ('name', 'sets', 'reps', 'rest', 'rir', 'intensification', 'muscle', 'remark',
                  'series_description', 'main_series', 'position'):
        if field in data:
            setattr(entry, field, data[field])
    db.session.commit()
    return jsonify(entry.to_dict())


@api_bp.delete('/program-exercises/<int:entry_id>')
@coach_required
def delete_exercise_entry(entry_id):
    entry = ExerciseEntry.query.get_or_404(entry_id)
    db.session.delete(entry)
    db.session.commit()
    return jsonify({'ok': True})


# ---------------------------------------------------------- EXERCISE BANK -

@api_bp.get('/exercise-bank')
@login_required
def list_exercise_bank():
    exercises = Exercise.query.order_by(Exercise.muscle_group, Exercise.name).all()
    return jsonify({
        'muscle_groups': MUSCLE_GROUPS,
        'exercises': [e.to_dict() for e in exercises],
    })


@api_bp.post('/exercise-bank')
@coach_required
def create_exercise_bank():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    muscle_group = data.get('muscle_group')
    if not name or muscle_group not in MUSCLE_GROUPS:
        return jsonify({'error': 'name et muscle_group (valide) requis'}), 400
    if Exercise.query.filter_by(name=name).first():
        return jsonify({'error': 'Cet exercice existe dÃ©jÃ '}), 409
    exercise = Exercise(name=name, muscle_group=muscle_group)
    db.session.add(exercise)
    db.session.commit()
    return jsonify(exercise.to_dict()), 201


@api_bp.put('/exercise-bank/<int:exercise_id>')
@coach_required
def update_exercise_bank(exercise_id):
    exercise = Exercise.query.get_or_404(exercise_id)
    data = request.get_json(silent=True) or {}
    if data.get('name'):
        exercise.name = data['name']
    if data.get('muscle_group') in MUSCLE_GROUPS:
        exercise.muscle_group = data['muscle_group']
    db.session.commit()
    return jsonify(exercise.to_dict())


@api_bp.delete('/exercise-bank/<int:exercise_id>')
@coach_required
def delete_exercise_bank(exercise_id):
    exercise = Exercise.query.get_or_404(exercise_id)
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
    if request.current_user.role != 'coach' and entry.athlete_id != request.current_user.id:
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
    if request.current_user.role != 'coach' and entry.athlete_id != request.current_user.id:
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
    if request.current_user.role != 'coach' and entry.athlete_id != request.current_user.id:
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
    if request.current_user.role != 'coach' and entry.athlete_id != request.current_user.id:
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


# -------------------------------------------------------------- FOOD BANK -

@api_bp.get('/foods')
@login_required
def list_foods():
    search = request.args.get('q')
    query = Food.query
    if search:
        query = query.filter(Food.name.ilike(f'%{search}%'))
    foods = query.order_by(Food.name).limit(500).all()
    return jsonify([f.to_dict() for f in foods])


@api_bp.post('/foods')
@coach_required
def create_food():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name or data.get('kcal') is None or data.get('carbs') is None:
        return jsonify({'error': 'name, kcal et carbs requis'}), 400
    if Food.query.filter_by(name=name).first():
        return jsonify({'error': 'Cet aliment existe dÃ©jÃ '}), 409

    food = Food(
        name=name, brand=data.get('brand'), kcal=data['kcal'], proteins=data.get('proteins'),
        lipids=data.get('lipids'), saturated_fats=data.get('saturated_fats'), carbs=data['carbs'],
        simple_sugars=data.get('simple_sugars'), fiber=data.get('fiber'), salt=data.get('salt'),
    )
    db.session.add(food)
    db.session.commit()
    return jsonify(food.to_dict()), 201


@api_bp.put('/foods/<int:food_id>')
@coach_required
def update_food(food_id):
    food = Food.query.get_or_404(food_id)
    data = request.get_json(silent=True) or {}
    for field in ('name', 'brand', 'kcal', 'proteins', 'lipids', 'saturated_fats', 'carbs',
                  'simple_sugars', 'fiber', 'salt'):
        if field in data:
            setattr(food, field, data[field])
    db.session.commit()
    return jsonify(food.to_dict())


@api_bp.delete('/foods/<int:food_id>')
@coach_required
def delete_food(food_id):
    food = Food.query.get_or_404(food_id)
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
    # Eager-load meals + foods : to_dict() calcule toujours les totaux via
    # get_daily_totals(), et with_meals=1 sert l'écran Nutrition en 1 seul
    # round-trip (évite le N+1 côté mobile qui timeout sur Railway).
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
    if request.current_user.role != 'coach' and plan.athlete_id != request.current_user.id:
        return jsonify({'error': 'AccÃ¨s refusÃ©'}), 403
    return jsonify(plan.to_dict(with_meals=True))


@api_bp.post('/meal-plans')
@coach_required
def create_meal_plan():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    athlete_id = data.get('athlete_id')
    if not name or not athlete_id:
        return jsonify({'error': 'name et athlete_id requis'}), 400
    has_any = MealPlan.query.filter_by(athlete_id=athlete_id).count() > 0
    plan = MealPlan(name=name, athlete_id=athlete_id, coach_id=request.current_user.id,
                     meal_count=data.get('meal_count', 6), is_active=not has_any)
    db.session.add(plan)
    db.session.commit()
    return jsonify(plan.to_dict()), 201


@api_bp.delete('/meal-plans/<int:plan_id>')
@coach_required
def delete_meal_plan(plan_id):
    plan = MealPlan.query.get_or_404(plan_id)
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
    """Mark a meal plan as the athlete's active diet (used by the Journal
    'diète respectée' shortcut to know which macros to apply)."""
    plan = MealPlan.query.get_or_404(plan_id)
    user = request.current_user
    if user.role != 'coach' and plan.athlete_id != user.id:
        return jsonify({'error': 'AccÃ¨s refusÃ©'}), 403
    MealPlan.query.filter_by(athlete_id=plan.athlete_id, is_active=True).update(
        {'is_active': False}, synchronize_session=False,
    )
    plan.is_active = True
    db.session.commit()
    return jsonify(plan.to_dict())


@api_bp.put('/meal-plans/<int:plan_id>')
@coach_required
def rename_meal_plan(plan_id):
    plan = MealPlan.query.get_or_404(plan_id)
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name requis'}), 400
    plan.name = name
    db.session.commit()
    return jsonify(plan.to_dict())


@api_bp.post('/meal-plans/<int:plan_id>/duplicate')
@coach_required
def duplicate_meal_plan(plan_id):
    source = MealPlan.query.get_or_404(plan_id)
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or f'{source.name} (copie)').strip()
    athlete_id = data.get('athlete_id') or source.athlete_id

    new_plan = MealPlan(
        name=name, athlete_id=athlete_id, coach_id=request.current_user.id,
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
@coach_required
def add_meal_entry(plan_id):
    MealPlan.query.get_or_404(plan_id)
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
@coach_required
def update_meal_entry(entry_id):
    entry = MealEntry.query.get_or_404(entry_id)
    data = request.get_json(silent=True) or {}
    if 'quantity' in data:
        entry.quantity = data['quantity']
    db.session.commit()
    return jsonify(entry.to_dict())


@api_bp.delete('/meal-entries/<int:entry_id>')
@coach_required
def delete_meal_entry(entry_id):
    entry = MealEntry.query.get_or_404(entry_id)
    db.session.delete(entry)
    db.session.commit()
    return jsonify({'ok': True})


@api_bp.put('/meal-plans/<int:plan_id>/meal-time')
@coach_required
def set_meal_time(plan_id):
    plan = MealPlan.query.get_or_404(plan_id)
    data = request.get_json(silent=True) or {}
    meal_number = data.get('meal_number')
    if meal_number not in range(1, 7):
        return jsonify({'error': 'meal_number doit Ãªtre entre 1 et 6'}), 400
    setattr(plan, f'meal_time_{meal_number}', data.get('time'))
    setattr(plan, f'meal_label_{meal_number}', data.get('label'))
    db.session.commit()
    return jsonify(plan.to_dict())


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

    athletes = User.query.filter_by(role='athlete').order_by(User.username).all()
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
    total_athletes = User.query.filter_by(role='athlete').count()
    marked = MobileWeeklyBilanMarking.query.filter_by(week_start=current_start, done=True).count()
    return jsonify({'unchecked_count': max(total_athletes - marked, 0)})

