import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'change_this_secret'
    # Utilise la variable d'environnement DATABASE_URL si définie,
    # sinon fallback vers MariaDB locale (mysql+pymysql)
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'mysql+pymysql://dru:dru_mdp@localhost:3306/flask_app_db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
