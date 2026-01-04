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
        
        # Fix Food table schema if needed (proteins and lipids should be nullable)
        try:
            from sqlalchemy import inspect
            from app.models import Food
            inspector = inspect(db.engine)
            food_columns = {col['name']: col for col in inspector.get_columns('food')}
            
            # Check if proteins column is nullable (it should be)
            if 'proteins' in food_columns and not food_columns['proteins']['nullable']:
                print("\n🔧 Fixing Food table schema (proteins/lipids should be nullable)...")
                db.session.execute(db.text("DROP TABLE IF EXISTS food"))
                db.session.commit()
                Food.__table__.create(db.engine)
                db.session.commit()
                print("✓ Food table schema fixed\n")
        except Exception as e:
            # Silently continue if schema check fails
            pass
        
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
        
        # Check if we need to seed - only check AFTER potential flush
        need_seed = False
        try:
            ex_count = db.session.query(Exercise).count()
            food_count = db.session.query(Food).count()
            need_seed = (ex_count == 0 or food_count == 0)
        except Exception:
            # If query fails, assume we need to seed
            need_seed = True
        
        if need_seed:
            print("\n📋 Seeding database...")
            try:
                from seeds import seed_all_data
                seed_all_data()
                # Force commit to persist all seeded data
                db.session.commit()
                # Verify after seeding
                ex_final = db.session.query(Exercise).count()
                food_final = db.session.query(Food).count()
                print(f"✓ Database seeded ({ex_final} exercises, {food_final} foods)\n")
            except Exception as e:
                print(f"⚠️ Seeding error (continuing): {e}\n")
                db.session.rollback()
    
    # Import routes after app is created to avoid circular imports
    from app import routes
    routes.register_routes(app)
    
    return app


