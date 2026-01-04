from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from app import db
from datetime import date, datetime

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(16), nullable=False, default='athlete')  # 'coach' ou 'athlete'

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    athlete = db.relationship('User', foreign_keys=[athlete_id], backref='programs_as_athlete')
    coach = db.relationship('User', foreign_keys=[coach_id], backref='programs_as_coach')
    sessions = db.relationship('ProgramSession', backref='program', cascade='all, delete-orphan', order_by='ProgramSession.day_of_week')

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

    def __repr__(self):
        return f'<JournalEntry {self.athlete_id} {self.entry_date}>'

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

    def __repr__(self):
        return f'<PerformanceEntry {self.exercise} series {self.series_number} on {self.entry_date}>'

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    athlete = db.relationship('User', foreign_keys=[athlete_id], backref='meal_plans_as_athlete')
    coach = db.relationship('User', foreign_keys=[coach_id], backref='meal_plans_as_coach')
    meals = db.relationship('MealEntry', backref='meal_plan', cascade='all, delete-orphan', order_by='MealEntry.meal_number')

    def __repr__(self):
        return f'<MealPlan {self.name} for {self.athlete_id}>'
    
    def get_daily_totals(self):
        """Calcule les totaux journaliers"""
        totals = {
            'kcals': 0,
            'proteins': 0,
            'lipids': 0,
            'carbs': 0
        }
        
        for meal in self.meals:
            if meal.food:
                quantity_factor = (meal.quantity or 100) / 100.0
                totals['kcals'] += (meal.food.kcal or 0) * quantity_factor
                totals['proteins'] += (meal.food.proteins or 0) * quantity_factor
                totals['lipids'] += (meal.food.lipids or 0) * quantity_factor
                totals['carbs'] += (meal.food.carbs or 0) * quantity_factor
        
        return totals


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
