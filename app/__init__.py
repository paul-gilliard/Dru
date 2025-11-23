import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from config import Config

db = SQLAlchemy()
migrate = Migrate()

# Global app reference - will be set by create_app()
app = None

def create_app():
    global app
    app = Flask(__name__)
    
    # Charger la configuration depuis config.py
    app.config.from_object(Config)
    
    db.init_app(app)
    migrate.init_app(app, db)
    
    # Import routes after app is created to avoid circular imports
    from app import routes
    
    return app
