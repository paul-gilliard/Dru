import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from config import Config

db = SQLAlchemy()
migrate = Migrate()

def create_app():
    app = Flask(__name__)
    
    # Charger la configuration depuis config.py
    app.config.from_object(Config)
    
    db.init_app(app)
    migrate.init_app(app, db)
    
    # Créer les tables au démarrage si elles n'existent pas
    with app.app_context():
        db.create_all()
        
        # Créer l'utilisateur admin par défaut s'il n'existe pas
        from app.models import User
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            print("Creating default admin user...")
            admin = User(username='admin', role='coach')
            admin.set_password(os.environ.get('ADMIN_PASSWORD', 'admin123'))
            db.session.add(admin)
            db.session.commit()
            print("✓ Admin user created")
    
    # Import routes after app is created to avoid circular imports
    from app import routes
    routes.register_routes(app)
    
    return app

