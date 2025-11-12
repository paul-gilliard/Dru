import os
from datetime import timedelta
from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

# exposer `app` au niveau du package pour que `from app import app` fonctionne
app = None

# ajouter les extensions
db = SQLAlchemy()
migrate = Migrate()

def create_app():
    global app
    app = Flask(__name__)

    # Charger la config de base
    app.config.from_object(Config)

    # Sécurité / cookie session (dev: SESSION_COOKIE_SECURE=False)
    app.permanent_session_lifetime = timedelta(days=7)
    app.config.setdefault('SESSION_COOKIE_HTTPONLY', True)
    app.config.setdefault('SESSION_COOKIE_SECURE', False)

    # Si une DATABASE_URL est fournie dans l'environnement, l'utiliser.
    # Sinon, si DB_USER/DB_PASS/DB_NAME sont définis, composer une URI mysql+pymysql.
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        db_user = os.environ.get('DB_USER')
        db_pass = os.environ.get('DB_PASS')
        db_host = os.environ.get('DB_HOST', 'localhost')
        db_port = os.environ.get('DB_PORT', '3306')
        db_name = os.environ.get('DB_NAME')
        if db_user and db_pass and db_name:
            db_url = f"mysql+pymysql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"

    if db_url:
        app.config['SQLALCHEMY_DATABASE_URI'] = db_url

    # initialiser les extensions
    db.init_app(app)
    migrate.init_app(app, db)

    # importer les routes après la création de `app`
    from app import routes

    # créer les tables si elles n'existent pas, puis l'utilisateur admin
    with app.app_context():
        db.create_all()
        from app.models import create_default_admin
        create_default_admin()

    return app