"""Athlète de démonstration : un par coach, jamais partagé entre coachs.

Un nouveau coach voit immédiatement à quoi ressemblent un programme rempli, un
journal tenu, des perfs qui bougent et un Easy Bilan exploitable. Cet athlète
ne compte pas dans le quota d'abonnement et le coach peut le supprimer
définitivement (`demo_seeded_at` empêche toute recréation ensuite).
"""

import secrets
from datetime import date, datetime, timedelta
from random import Random

from app import db
from app.models import (
    Exercise, ExerciseEntry, Food, JournalEntry, MealEntry, MealPlan,
    Objective, PerformanceEntry, Program, ProgramSession, User,
)

DEMO_DISPLAY_NAME = 'Alex Démo'
DEMO_EMAIL_TEMPLATE = 'demo.athlete.{coach_id}@farmness.demo'
DEMO_PROGRAM_NAME = 'PPL — Sèche 4 semaines'
DEMO_PLAN_NAME = 'Sèche 2450 kcal'
WEEKS = 4
WEIGHT_START = 82.4
WEIGHT_LOSS = 2.0

# (nom, séries, reps cibles, repos, RIR, muscle, charge de départ, tendance)
# tendance : 'up' = progresse, 'down' = régresse, 'flat' = stagne.
PPL_SESSIONS = [
    (0, 'Push A — Pecs / Épaules / Triceps', [
        ('Développé couché', 4, '6-8', '2:30', '1-2', 'PEC', 82.5, 'up'),
        ('Développé militaire', 3, '8-10', '2:00', '2', 'EPAULES', 45.0, 'up'),
        ('Écarté couché', 3, '10-12', '1:30', '1', 'PEC', 16.0, 'flat'),
        ('Élévation latérale haltères', 4, '12-15', '1:00', '0-1', 'EPAULES', 10.0, 'flat'),
        ('Pushdown triceps', 3, '12-15', '1:00', '1', 'TRICEPS', 32.5, 'up'),
    ]),
    (1, 'Pull A — Dos / Biceps', [
        ('Traction barre', 4, '6-8', '2:30', '1-2', 'DOS', 5.0, 'up'),
        ('Rowing barre', 4, '8-10', '2:00', '2', 'DOS', 70.0, 'up'),
        ('Tirage poitrine', 3, '10-12', '1:30', '1', 'DOS', 60.0, 'flat'),
        ('Face pull', 3, '15', '1:00', '1', 'EPAULES', 22.5, 'flat'),
        ('Curl barre droite', 3, '10-12', '1:30', '1', 'BICEPS', 32.5, 'down'),
    ]),
    (2, 'Legs A — Quadri dominante', [
        ('Squat barre', 4, '5-6', '3:00', '2', 'LEGS', 105.0, 'up'),
        ('Presse à cuisses', 3, '10-12', '2:00', '1-2', 'LEGS', 180.0, 'up'),
        ('Leg extension', 3, '12-15', '1:30', '1', 'QUAD', 55.0, 'flat'),
        ('Leg curl machine', 3, '10-12', '1:30', '1', 'ISCHIO', 45.0, 'down'),
        ('Relevé mollet debout', 4, '12-15', '1:00', '0-1', 'MOLLET', 90.0, 'down'),
    ]),
    (3, 'Push B — Volume / Congestion', [
        ('Décliné haltère', 4, '8-10', '2:00', '1-2', 'PEC', 30.0, 'up'),
        ('Machine épaules', 3, '10-12', '1:30', '1', 'EPAULES', 40.0, 'flat'),
        ('Peck deck', 3, '12-15', '1:15', '1', 'PEC', 50.0, 'down'),
        ('Élévation latérale panatta', 3, '15', '1:00', '0-1', 'EPAULES', 12.5, 'flat'),
        ('Extension triceps poulie haute', 3, '12-15', '1:00', '1', 'TRICEPS', 27.5, 'flat'),
    ]),
    (4, 'Pull B — Épaisseur dos', [
        ('Lat pulldown', 4, '8-10', '2:00', '1-2', 'DOS', 65.0, 'up'),
        ('Rowing haltère', 3, '10-12', '1:30', '1', 'DOS', 34.0, 'up'),
        ('Shrugs haltères', 3, '12-15', '1:00', '1', 'EPAULES', 30.0, 'flat'),
        ('Curl haltères', 3, '10-12', '1:30', '1', 'BICEPS', 14.0, 'flat'),
        ('Curl machine', 3, '12-15', '1:00', '0-1', 'BICEPS', 25.0, 'down'),
    ]),
    (5, 'Legs B — Chaîne postérieure', [
        ('Squat hack machine', 4, '8-10', '2:30', '1-2', 'LEGS', 90.0, 'up'),
        ('Curl jambes debout', 3, '10-12', '1:30', '1', 'ISCHIO', 25.0, 'flat'),
        ('Fente avec haltères', 3, '10-12', '1:30', '1-2', 'LEGS', 20.0, 'up'),
        ('Relevé mollet machine', 4, '15', '1:00', '0-1', 'MOLLET', 70.0, 'flat'),
        ('Crunch machine', 3, '15', '1:00', '1', 'ABDOS', 35.0, 'flat'),
    ]),
]

# (heure, libellé, [(nom aliment, grammes)])
DEMO_MEALS = [
    ('07:30', 'Petit-déjeuner', [('Avoine', 100), ('Œuf (plein air, Marque repère)', 150), ('Banane', 120)]),
    ('12:30', 'Déjeuner', [
        ('Blanc de Poulet', 210), ('Riz Basmati (Marque repère)', 120),
        ('Brocoli', 200), ("Huile d'olive", 10),
    ]),
    ('16:30', 'Collation', [('Fromage blanc 0% Marque repère', 300), ('Amandes', 25)]),
    ('20:00', 'Dîner', [('Saumon en pavé', 180), ('Patate douce', 260), ('Carotte', 150)]),
]

DEMO_OBJECTIVES = [
    ('Descendre à 79 kg sans perdre de force', 'Sèche progressive : -0,4 kg par semaine max, protéines hautes.'),
    ('Passer 100 kg × 8 au développé couché', 'Série principale en 6-8 reps, +2,5 kg dès que 8 reps sont propres.'),
    ('6 séances PPL par semaine, sans en sauter', 'Priorité à la régularité avant le volume.'),
]

DIGESTIONS = ['Bonne', 'Normale', 'Ballonnements légers', 'Très bonne']
FOOD_QUALITIES = ['Bonne', 'Correcte', 'Écart le soir', 'Très bonne']


def _week_start(d):
    return d - timedelta(days=d.weekday())


def _load_step(base):
    """Incrément hebdo réaliste sur un bloc de 4 semaines, selon le matériel."""
    if base >= 150:
        return 5.0
    if base >= 80:
        return 2.5
    if base >= 40:
        return 1.25
    return 0.5


def _week_load(base, trend, week_index):
    step = _load_step(base)
    if trend == 'up':
        return base + step * week_index
    if trend == 'down':
        return max(round(base * 0.7, 1), base - step * week_index)
    return base


def _reps_target(reps):
    """Premier nombre de la fourchette ('8-10' → 8)."""
    digits = ''
    for ch in reps or '':
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    return int(digits) if digits else 10


def is_demo_athlete(user):
    return bool(user is not None and user.role == 'athlete' and user.is_demo)


def demo_athlete_of(coach_id):
    return User.query.filter_by(role='athlete', coach_id=coach_id, is_demo=True).first()


def _ensure_common_exercise(name, muscle):
    """L'exercice doit exister en banque commune pour le tonnage par muscle."""
    existing = Exercise.query.filter_by(name=name).first()
    if existing:
        return existing
    exercise = Exercise(name=name, muscle_group=muscle, owner_id=None)
    db.session.add(exercise)
    return exercise


def _seed_program(athlete, coach):
    program = Program(
        name=DEMO_PROGRAM_NAME, athlete_id=athlete.id, coach_id=coach.id, is_active=True,
    )
    db.session.add(program)
    db.session.flush()

    sessions_by_day = {}
    for day, session_name, exercises in PPL_SESSIONS:
        session = ProgramSession(program_id=program.id, day_of_week=day, session_name=session_name)
        db.session.add(session)
        db.session.flush()
        sessions_by_day[day] = session
        for position, (name, sets, reps, rest, rir, muscle, _base, _trend) in enumerate(exercises):
            _ensure_common_exercise(name, muscle)
            db.session.add(ExerciseEntry(
                session_id=session.id, position=position, name=name, sets=sets, reps=reps,
                rest=rest, rir=rir, muscle=muscle, main_series=1,
            ))
    return program, sessions_by_day


def _seed_journal(athlete, first_day, today, rng):
    total_days = (today - first_day).days
    daily_loss = WEIGHT_LOSS / total_days if total_days else 0
    skipped = 0

    day = first_day
    while day <= today:
        elapsed = (day - first_day).days
        # 2 oublis sur les 3 premières semaines : le coach voit un suivi réaliste.
        if skipped < 2 and day < today - timedelta(days=7) and rng.random() < 0.09:
            skipped += 1
            day += timedelta(days=1)
            continue

        weekend = day.weekday() >= 5
        progress = elapsed / total_days if total_days else 1
        weight = WEIGHT_START - daily_loss * elapsed
        # Bornes exactes : le coach doit lire -2,0 kg entre le premier et le dernier jour.
        if day != first_day and day != today:
            weight += rng.uniform(-0.22, 0.22)
        db.session.add(JournalEntry(
            athlete_id=athlete.id,
            entry_date=day,
            weight=round(weight, 1),
            kcals=int(rng.uniform(2330, 2560) + (180 if weekend else 0)),
            protein=int(rng.uniform(168, 190)),
            carbs=int(rng.uniform(225, 285) + (30 if weekend else 0)),
            fats=int(rng.uniform(58, 78)),
            water_ml=round(rng.uniform(2300, 3400), 0),
            steps=int(rng.uniform(5800, 8200) if weekend else rng.uniform(8200, 12500)),
            sleep_hours=round(rng.uniform(6.4, 8.4), 1),
            energy=max(3, min(9, int(round(6 + progress * 1.5 + rng.uniform(-1.2, 1.2))))),
            stress=max(1, min(8, int(round(5 - progress * 1.2 + rng.uniform(-1.2, 1.2))))),
            hunger=max(2, min(9, int(round(4 + progress * 2.2 + rng.uniform(-1, 1))))),
            digestion=rng.choice(DIGESTIONS),
            food_quality=rng.choice(FOOD_QUALITIES),
        ))
        day += timedelta(days=1)


def _seed_performances(athlete, sessions_by_day, first_monday, today, rng):
    for week_index in range(WEEKS):
        week_start = first_monday + timedelta(days=7 * week_index)
        for day, _session_name, exercises in PPL_SESSIONS:
            entry_date = week_start + timedelta(days=day)
            if entry_date > today:
                continue
            session = sessions_by_day.get(day)
            for name, sets, reps, _rest, _rir, _muscle, base, trend in exercises:
                load = _week_load(base, trend, week_index)
                target = _reps_target(reps)
                for series in range(1, (sets or 3) + 1):
                    # Reps qui s'effritent série après série, un peu plus vite si ça régresse.
                    done = target - (series - 1)
                    if trend == 'down' and week_index:
                        done -= 1
                    elif trend == 'up' and week_index and series == 1:
                        done += 1
                    done = max(3, done + rng.choice([-1, 0, 0, 0]))
                    rpe = min(10, 7 + series - 1 + (1 if trend == 'down' else 0))
                    db.session.add(PerformanceEntry(
                        athlete_id=athlete.id,
                        entry_date=entry_date,
                        program_session_id=session.id if session else None,
                        exercise=name,
                        series_number=series,
                        reps=float(done),
                        load=round(load, 2),
                        rpe=rpe,
                    ))


def _seed_meal_plan(athlete, coach):
    plan = MealPlan(
        name=DEMO_PLAN_NAME, athlete_id=athlete.id, coach_id=coach.id, is_active=True,
        meal_count=len(DEMO_MEALS),
    )
    for index, (time_label, label, _foods) in enumerate(DEMO_MEALS, start=1):
        setattr(plan, f'meal_time_{index}', time_label)
        setattr(plan, f'meal_label_{index}', label)
    db.session.add(plan)
    db.session.flush()

    for meal_number, (_time_label, _label, foods) in enumerate(DEMO_MEALS, start=1):
        position = 0
        for food_name, grams in foods:
            food = (
                Food.query.filter_by(name=food_name).first()
                # La banque commune évolue : on retombe sur un aliment approchant.
                or Food.query.filter(Food.name.ilike(f'{food_name.split(" (")[0]}%')).first()
            )
            if not food:
                continue
            db.session.add(MealEntry(
                meal_plan_id=plan.id, food_id=food.id, meal_number=meal_number,
                quantity=float(grams), position=position,
            ))
            position += 1
    return plan


def ensure_demo_athlete(coach, commit=True):
    """Crée l'athlète démo du coach s'il n'en a jamais eu. Idempotent."""
    if coach is None or coach.role != 'coach':
        return None
    if coach.demo_seeded_at is not None:
        return demo_athlete_of(coach.id)

    email = DEMO_EMAIL_TEMPLATE.format(coach_id=coach.id)
    if User.query.filter(db.func.lower(User.username) == email).first():
        coach.demo_seeded_at = datetime.utcnow()
        if commit:
            db.session.commit()
        return demo_athlete_of(coach.id)

    today = date.today()
    first_monday = _week_start(today) - timedelta(days=7 * (WEEKS - 1))
    rng = Random(coach.id * 7919 + 13)

    athlete = User(
        username=email,
        email=email,
        role='athlete',
        display_name=DEMO_DISPLAY_NAME,
        coach_id=coach.id,
        coach_associated_at=datetime.utcnow(),
        is_demo=True,
        independent_module=False,
        bilan_weekday=6,
    )
    athlete.set_password(secrets.token_urlsafe(24))
    db.session.add(athlete)
    db.session.flush()

    _program, sessions_by_day = _seed_program(athlete, coach)
    _seed_journal(athlete, first_monday, today, rng)
    _seed_performances(athlete, sessions_by_day, first_monday, today, rng)
    _seed_meal_plan(athlete, coach)
    for title, description in DEMO_OBJECTIVES:
        db.session.add(Objective(athlete_id=athlete.id, title=title, description=description))

    coach.demo_seeded_at = datetime.utcnow()
    if commit:
        db.session.commit()
    return athlete
