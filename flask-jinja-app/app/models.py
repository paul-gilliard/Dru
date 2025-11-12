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

    def __repr__(self):
        return f'<Exercise {self.name} ({self.session_id})>'

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
    sets = db.Column(db.Integer, nullable=True)
    reps = db.Column(db.Float, nullable=True)  # now float (ex: 6.5)
    load = db.Column(db.Float, nullable=True)  # poids
    rpe = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    athlete = db.relationship('User', backref='performance_entries')
    program_session = db.relationship('ProgramSession', backref='performance_entries', foreign_keys=[program_session_id])

    def __repr__(self):
        return f'<PerformanceEntry {self.exercise} on {self.entry_date}>'

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