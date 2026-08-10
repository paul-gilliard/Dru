from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from app import db
from datetime import date, datetime

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default='athlete')  # 'coach' ou 'athlete'
    display_name = db.Column(db.String(128), nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'role': self.role,
            'display_name': self.display_name or self.username,
        }

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'

class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

    def __repr__(self):
        return f'<Role {self.name}>'

class Availability(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    location = db.Column(db.String(128), nullable=False, default='boutique biotech merignac')
    timeslot = db.Column(db.String(16), nullable=False, default='morning')  # 'morning' / 'afternoon' / 'day'
    available = db.Column(db.Boolean, nullable=False, default=True)

    __table_args__ = (
        db.UniqueConstraint('date', 'location', 'timeslot', name='uq_date_location_timeslot'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'location': self.location,
            'timeslot': self.timeslot,
            'available': bool(self.available)
        }

class Program(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    athlete_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    coach_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    athlete = db.relationship('User', foreign_keys=[athlete_id], backref='programs_as_athlete')
    coach = db.relationship('User', foreign_keys=[coach_id], backref='programs_as_coach')
    sessions = db.relationship('ProgramSession', backref='program', cascade='all, delete-orphan', order_by='ProgramSession.day_of_week')

    def to_dict(self, with_sessions=False):
        data = {
            'id': self.id,
            'name': self.name,
            'athlete_id': self.athlete_id,
            'coach_id': self.coach_id,
            'is_active': bool(self.is_active),
        }
        if with_sessions:
            data['sessions'] = [s.to_dict() for s in self.sessions]
        return data

    def __repr__(self):
        return f'<Program {self.name} for {self.athlete_id}>'

class ProgramSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    program_id = db.Column(db.Integer, db.ForeignKey('program.id'), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0 = Monday .. 6 = Sunday
    session_name = db.Column(db.String(128), nullable=True)
    exercises = db.relationship('ExerciseEntry', backref='session', cascade='all, delete-orphan', order_by='ExerciseEntry.position')

    __table_args__ = (
        db.UniqueConstraint('program_id', 'day_of_week', name='uq_program_day'),
    )

    def to_dict(self, with_exercises=True):
        data = {
            'id': self.id,
            'program_id': self.program_id,
            'day_of_week': self.day_of_week,
            'session_name': self.session_name,
        }
        if with_exercises:
            data['exercises'] = [e.to_dict() for e in self.exercises]
        return data

    def __repr__(self):
        return f'<ProgramSession {self.program_id} day {self.day_of_week}>'

class ExerciseEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('program_session.id'), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)  # order in session
    name = db.Column(db.String(192), nullable=False)
    sets = db.Column(db.Integer, nullable=True)
    reps = db.Column(db.String(64), nullable=True)        # ex: "8-12"
    rest = db.Column(db.String(64), nullable=True)        # ex: "long", "60s"
    rir = db.Column(db.String(32), nullable=True)
    intensification = db.Column(db.String(64), nullable=True)
    muscle = db.Column(db.String(64), nullable=True)
    remark = db.Column(db.Text, nullable=True)
    series_description = db.Column(db.Text, nullable=True)  # ex: "S1: 8 reps 100kg\nS2: 6 reps 120kg\nS3: 4 reps 140kg"
    main_series = db.Column(db.Integer, nullable=True)  # numéro de la série principale (1, 2, 3, etc.)

    def __repr__(self):
        return f'<Exercise {self.name} ({self.session_id})>'
    
    def get_series_list(self):
        """Parse series_description and return list of series"""
        if not self.series_description:
            return []
        lines = self.series_description.strip().split('\n')
        series = []
        for i, line in enumerate(lines, 1):
            series.append({
                'number': i,
                'description': line.strip(),
                'text': f'Série {i}: {line.strip()}',
                'is_main': i == self.main_series
            })
        return series
    
    @property
    def series_count(self):
        """Return number of series"""
        return len(self.get_series_list())

    def to_dict(self):
        return {
            'id': self.id,
            'session_id': self.session_id,
            'position': self.position,
            'name': self.name,
            'sets': self.sets,
            'reps': self.reps,
            'rest': self.rest,
            'rir': self.rir,
            'intensification': self.intensification,
            'muscle': self.muscle,
            'remark': self.remark,
            'series_description': self.series_description,
            'main_series': self.main_series,
            'series': self.get_series_list(),
        }

class JournalEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    entry_date = db.Column(db.Date, nullable=False, index=True)

    # types forcés
    weight = db.Column(db.Float, nullable=True)         # float
    protein = db.Column(db.Integer, nullable=True)      # int
    carbs = db.Column(db.Integer, nullable=True)        # int
    fats = db.Column(db.Integer, nullable=True)         # int
    kcals = db.Column(db.Integer, nullable=True)        # int
    water_ml = db.Column(db.Float, nullable=True)       # float
    steps = db.Column(db.Integer, nullable=True)        # int
    sleep_hours = db.Column(db.Float, nullable=True)    # float

    digestion = db.Column(db.String(128), nullable=True)     # free text
    energy = db.Column(db.Integer, nullable=True)            # int 0-10
    stress = db.Column(db.Integer, nullable=True)            # int 0-10
    hunger = db.Column(db.Integer, nullable=True)            # int 0-10
    food_quality = db.Column(db.String(64), nullable=True)   # keep string (or change to int if desired)

    menstrual_cycle = db.Column(db.String(64), nullable=True) # values constrained in form
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    athlete = db.relationship('User', backref='journal_entries')

    __table_args__ = (
        db.Index('idx_journal_athlete_date', 'athlete_id', 'entry_date'),
    )

    def __repr__(self):
        return f'<JournalEntry {self.athlete_id} {self.entry_date}>'

    def to_dict(self):
        return {
            'id': self.id,
            'athlete_id': self.athlete_id,
            'entry_date': self.entry_date.isoformat(),
            'weight': self.weight,
            'protein': self.protein,
            'carbs': self.carbs,
            'fats': self.fats,
            'kcals': self.kcals,
            'water_ml': self.water_ml,
            'steps': self.steps,
            'sleep_hours': self.sleep_hours,
            'digestion': self.digestion,
            'energy': self.energy,
            'stress': self.stress,
            'hunger': self.hunger,
            'food_quality': self.food_quality,
            'menstrual_cycle': self.menstrual_cycle,
        }

class PerformanceEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    entry_date = db.Column(db.Date, nullable=False, index=True)
    program_session_id = db.Column(db.Integer, db.ForeignKey('program_session.id'), nullable=True)
    exercise = db.Column(db.String(192), nullable=False)
    series_number = db.Column(db.Integer, nullable=True)  # numéro de la série (1, 2, 3, etc.)
    reps = db.Column(db.Float, nullable=True)  # now float (ex: 6.5)
    load = db.Column(db.Float, nullable=True)  # poids
    rpe = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    athlete = db.relationship('User', backref='performance_entries')
    program_session = db.relationship('ProgramSession', backref='performance_entries', foreign_keys=[program_session_id])

    __table_args__ = (
        db.Index('idx_perf_athlete_date', 'athlete_id', 'entry_date'),
        db.Index('idx_perf_athlete_exercise_date', 'athlete_id', 'exercise', 'entry_date'),
    )

    def __repr__(self):
        return f'<PerformanceEntry {self.exercise} series {self.series_number} on {self.entry_date}>'

    def to_dict(self):
        return {
            'id': self.id,
            'athlete_id': self.athlete_id,
            'entry_date': self.entry_date.isoformat(),
            'program_session_id': self.program_session_id,
            'exercise': self.exercise,
            'series_number': self.series_number,
            'reps': self.reps,
            'load': self.load,
            'rpe': self.rpe,
            'notes': self.notes,
        }

def create_default_admin():
    """
    Crée un utilisateur admin/admin si aucun 'admin' n'existe.
    Appeler depuis create_app() avec le contexte d'application actif.
    """
    if not User.query.filter_by(username='admin').first():
        u = User(username='admin', role='coach')
        u.set_password('admin')
        db.session.add(u)
        db.session.commit()


# Muscles groups disponibles
MUSCLE_GROUPS = [
    'ABDOS',
    'BICEPS',
    'DOS',
    'EPAULES',
    'ISCHIO',
    'LEGS',
    'MOLLET',
    'PEC',
    'QUAD'
]


class Exercise(db.Model):
    """Banque d'exercices"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(192), nullable=False, unique=True)
    muscle_group = db.Column(db.String(64), nullable=False)  # Une des valeurs de MUSCLE_GROUPS
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Exercise {self.name} ({self.muscle_group})>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'muscle_group': self.muscle_group
        }

class Food(db.Model):
    """Banque d'aliments"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(192), nullable=False, unique=True)
    brand = db.Column(db.String(100), nullable=True)
    kcal = db.Column(db.Float, nullable=False)
    proteins = db.Column(db.Float)
    lipids = db.Column(db.Float)
    saturated_fats = db.Column(db.Float)
    carbs = db.Column(db.Float, nullable=False)
    simple_sugars = db.Column(db.Float)
    fiber = db.Column(db.Float)
    salt = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Food {self.name} ({self.kcal} kcal)>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'brand': self.brand,
            'kcal': self.kcal,
            'proteins': self.proteins,
            'lipids': self.lipids,
            'saturated_fats': self.saturated_fats,
            'carbs': self.carbs,
            'simple_sugars': self.simple_sugars,
            'fiber': self.fiber,
            'salt': self.salt
        }


class MealPlan(db.Model):
    """Plan alimentaire pour un athlète"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    athlete_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    coach_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    meal_time_1 = db.Column(db.String(5), nullable=True)  # e.g. "08:00"
    meal_time_2 = db.Column(db.String(5), nullable=True)
    meal_time_3 = db.Column(db.String(5), nullable=True)
    meal_time_4 = db.Column(db.String(5), nullable=True)
    meal_time_5 = db.Column(db.String(5), nullable=True)
    meal_time_6 = db.Column(db.String(5), nullable=True)
    meal_label_1 = db.Column(db.String(100), nullable=True)
    meal_label_2 = db.Column(db.String(100), nullable=True)
    meal_label_3 = db.Column(db.String(100), nullable=True)
    meal_label_4 = db.Column(db.String(100), nullable=True)
    meal_label_5 = db.Column(db.String(100), nullable=True)
    meal_label_6 = db.Column(db.String(100), nullable=True)
    meal_count = db.Column(db.Integer, default=6, nullable=True)  # nb de repas actifs (1-6)

    athlete = db.relationship('User', foreign_keys=[athlete_id], backref='meal_plans_as_athlete')
    coach = db.relationship('User', foreign_keys=[coach_id], backref='meal_plans_as_coach')
    meals = db.relationship('MealEntry', backref='meal_plan', cascade='all, delete-orphan', order_by='MealEntry.meal_number')

    def __repr__(self):
        return f'<MealPlan {self.name} for {self.athlete_id}>'
    
    def get_daily_totals(self):
        """Calcule les totaux journaliers"""
        totals = {
            'kcals': 0, 'proteins': 0, 'lipids': 0, 'carbs': 0,
            'saturated_fats': 0, 'simple_sugars': 0, 'fiber': 0, 'salt': 0
        }
        
        for meal in self.meals:
            if meal.food:
                quantity_factor = (meal.quantity or 100) / 100.0
                totals['kcals'] += (meal.food.kcal or 0) * quantity_factor
                totals['proteins'] += (meal.food.proteins or 0) * quantity_factor
                totals['lipids'] += (meal.food.lipids or 0) * quantity_factor
                totals['carbs'] += (meal.food.carbs or 0) * quantity_factor
                totals['saturated_fats'] += (meal.food.saturated_fats or 0) * quantity_factor
                totals['simple_sugars'] += (meal.food.simple_sugars or 0) * quantity_factor
                totals['fiber'] += (meal.food.fiber or 0) * quantity_factor
                totals['salt'] += (meal.food.salt or 0) * quantity_factor
        
        return totals

    def to_dict(self, with_meals=True):
        totals = self.get_daily_totals()
        data = {
            'id': self.id,
            'name': self.name,
            'athlete_id': self.athlete_id,
            'coach_id': self.coach_id,
            'is_active': bool(self.is_active),
            'meal_count': self.meal_count or 6,
            'meal_times': [getattr(self, f'meal_time_{i}') for i in range(1, 7)],
            'meal_labels': [getattr(self, f'meal_label_{i}') for i in range(1, 7)],
            'totals': {
                'kcals': totals['kcals'],
                'proteins': totals['proteins'],
                'lipids': totals['lipids'],
                'carbs': totals['carbs'],
            },
        }
        if with_meals:
            meals_by_number = {}
            for m in self.meals:
                meals_by_number.setdefault(m.meal_number, []).append(m.to_dict())
            data['meals_by_number'] = meals_by_number
        return data


class MealEntry(db.Model):
    """Entrée aliment dans un plan alimentaire"""
    id = db.Column(db.Integer, primary_key=True)
    meal_plan_id = db.Column(db.Integer, db.ForeignKey('meal_plan.id'), nullable=False)
    food_id = db.Column(db.Integer, db.ForeignKey('food.id'), nullable=False)
    meal_number = db.Column(db.Integer, nullable=False)  # 1-6 pour Repas 1-6
    quantity = db.Column(db.Float, default=100)  # en grammes
    position = db.Column(db.Integer, default=0)  # ordre dans le repas
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    food = db.relationship('Food', backref='meal_entries')

    __table_args__ = (
        db.UniqueConstraint('meal_plan_id', 'food_id', 'meal_number', 'position', name='uq_meal_entry'),
    )

    def __repr__(self):
        return f'<MealEntry {self.food.name} ({self.quantity}g) Meal {self.meal_number}>'
    
    def to_dict(self):
        quantity_factor = (self.quantity or 100) / 100.0
        return {
            'id': self.id,
            'food_id': self.food_id,
            'food_name': self.food.name if self.food else '',
            'meal_number': self.meal_number,
            'quantity': self.quantity,
            'kcals': (self.food.kcal or 0) * quantity_factor if self.food else 0,
            'proteins': (self.food.proteins or 0) * quantity_factor if self.food else 0,
            'lipids': (self.food.lipids or 0) * quantity_factor if self.food else 0,
            'carbs': (self.food.carbs or 0) * quantity_factor if self.food else 0
        }

class WeeklyBilanMarking(db.Model):
    """Track which athletes have had their weekly bilan reviewed by a coach"""
    id = db.Column(db.Integer, primary_key=True)
    coach_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    week_start = db.Column(db.Date, nullable=False, index=True)  # Monday of the week
    marked_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)  # marked_at + 7 days
    
    # Relationships
    coach = db.relationship('User', foreign_keys=[coach_id], backref='markings_made')
    athlete = db.relationship('User', foreign_keys=[athlete_id], backref='markings_received')
    
    __table_args__ = (
        db.UniqueConstraint('coach_id', 'athlete_id', 'week_start', name='uq_coach_athlete_week'),
    )
    
    def is_expired(self):
        return datetime.utcnow() > self.expires_at
    
    def __repr__(self):
        return f'<WeeklyBilanMarking coach={self.coach_id} athlete={self.athlete_id} week={self.week_start}>'

class Objective(db.Model):
    """Objectives for athletes"""
    id = db.Column(db.Integer, primary_key=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    title = db.Column(db.String(256), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow, nullable=False, default=datetime.utcnow)
    
    # Relationship
    athlete = db.relationship('User', foreign_keys=[athlete_id], backref='objectives')
    
    def __repr__(self):
        return f'<Objective {self.title} for athlete={self.athlete_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'athlete_id': self.athlete_id,
            'title': self.title,
            'description': self.description,
        }


class MobileWeeklyBilanMarking(db.Model):
    """Markings Easy Bilan Hebdo for the mobile app (separate table from web WeeklyBilanMarking)."""
    __tablename__ = 'mobile_weekly_bilan_marking'
    id = db.Column(db.Integer, primary_key=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    week_start = db.Column(db.Date, nullable=False, index=True)
    done = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('athlete_id', 'week_start', name='uq_mobile_bilan_athlete_week'),
        )

    def to_dict(self):
        return {
            'id': self.id,
            'athlete_id': self.athlete_id,
            'week_start': self.week_start.isoformat(),
            'done': bool(self.done),
        }
