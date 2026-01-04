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
        # En production, supprimer et recréer les tables si nécessaire
        # (à utiliser une seule fois lors du nettoyage)
        if os.environ.get('RECREATE_DB') == 'true':
            print("⚠️ Dropping all tables...")
            db.drop_all()
            print("✓ Dropped")
        
        print("Creating database tables...")
        db.create_all()
        print("✓ Database tables created")
        
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
        
        # Seed exercises and foods if tables are empty
        from app.models import Exercise, Food
        if Exercise.query.count() == 0 or Food.query.count() == 0:
            print("\n📋 Seeding database...")
            try:
                from seeds import seed_all_data
                seed_all_data()
                print("✓ Database seeded\n")
            except Exception as e:
                print(f"⚠️ Seeding error (continuing): {e}\n")
                db.session.rollback()
    
    # Import routes after app is created to avoid circular imports
    from app import routes
    routes.register_routes(app)
    
    return app


