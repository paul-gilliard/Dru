import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    """Configuration de base pour Flask"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-change-in-prod'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Configuration de la base de données
    # En production (Railway): DATABASE_URL sera défini comme variable d'environnement
    # En local (XAMPP): utilise les paramètres locaux
    DB_USER = os.environ.get('DB_USER') or 'root'
    DB_PASSWORD = os.environ.get('DB_PASSWORD') or ''  # vide pour XAMPP par défaut
    DB_HOST = os.environ.get('DB_HOST') or 'localhost'
    DB_PORT = os.environ.get('DB_PORT') or '3306'
    DB_NAME = os.environ.get('DB_NAME') or 'flask_app_db'
    
    # Construction de l'URI SQLAlchemy
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        f'mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'


class DevelopmentConfig(Config):
    """Configuration pour le développement local (XAMPP)"""
    DEBUG = True
    DB_USER = 'root'
    DB_PASSWORD = ''
    DB_HOST = 'localhost'
    DB_PORT = '3306'
    DB_NAME = 'flask_app_db'
    SQLALCHEMY_DATABASE_URI = f'mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'


class ProductionConfig(Config):
    """Configuration pour la production (Railway avec MariaDB)"""
    DEBUG = False
    # En production, utilise DATABASE_URL depuis les variables d'environnement Railway
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')


# Sélection de la configuration selon l'environnement
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}

# Utiliser la config selon l'environnement (défaut: development)
FLASK_ENV = os.environ.get('FLASK_ENV', 'development')
Config = config.get(FLASK_ENV, config['default'])
