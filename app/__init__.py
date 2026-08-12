import os
from datetime import datetime
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from config import Config

db = SQLAlchemy()
migrate = Migrate()

def create_app():
    app = Flask(__name__)
    
    # Charger la configuration depuis config.py
    app.config.from_object(Config)
    
    db.init_app(app)
    migrate.init_app(app, db)
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    
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

        # Add meal_time columns to meal_plan if they don't exist
        try:
            from sqlalchemy import inspect as sa_inspect
            inspector2 = sa_inspect(db.engine)
            mp_columns = {col['name'] for col in inspector2.get_columns('meal_plan')}
            for i in range(1, 7):
                if f'meal_time_{i}' not in mp_columns:
                    db.session.execute(db.text(f"ALTER TABLE meal_plan ADD COLUMN meal_time_{i} VARCHAR(5) NULL"))
                if f'meal_label_{i}' not in mp_columns:
                    db.session.execute(db.text(f"ALTER TABLE meal_plan ADD COLUMN meal_label_{i} VARCHAR(100) NULL"))
            # Add brand to food if missing
            food_columns = {col['name'] for col in inspector2.get_columns('food')}
            if 'brand' not in food_columns:
                db.session.execute(db.text("ALTER TABLE food ADD COLUMN brand VARCHAR(100) NULL"))
            # Add meal_count to meal_plan if missing
            if 'meal_count' not in mp_columns:
                db.session.execute(db.text("ALTER TABLE meal_plan ADD COLUMN meal_count INT DEFAULT 6"))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Mobile API compat: display_name + password_hash width
        try:
            from sqlalchemy import inspect as sa_inspect3
            inspector3 = sa_inspect3(db.engine)
            user_columns = {col['name']: col for col in inspector3.get_columns('user')}
            if 'display_name' not in user_columns:
                db.session.execute(db.text("ALTER TABLE `user` ADD COLUMN display_name VARCHAR(128) NULL"))
            # Widen password_hash if still VARCHAR(128) — werkzeug hashes can exceed 128 chars
            db.session.execute(db.text("ALTER TABLE `user` MODIFY COLUMN password_hash VARCHAR(255) NOT NULL"))
            db.session.commit()
            print("✓ User table mobile-compat OK")
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ User mobile-compat alter skipped: {e}")

        # Active program flag for athlete home / week view
        try:
            from sqlalchemy import inspect as sa_inspect4
            inspector4 = sa_inspect4(db.engine)
            program_columns = {col['name'] for col in inspector4.get_columns('program')}
            if 'is_active' not in program_columns:
                db.session.execute(db.text(
                    "ALTER TABLE program ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 0"
                ))
                db.session.commit()
                print("✓ program.is_active added")
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ program.is_active alter skipped: {e}")

        # Active meal plan flag (diet-compliance shortcut in mobile Journal)
        try:
            from sqlalchemy import inspect as sa_inspect5
            inspector5 = sa_inspect5(db.engine)
            mealplan_columns = {col['name'] for col in inspector5.get_columns('meal_plan')}
            if 'is_active' not in mealplan_columns:
                db.session.execute(db.text(
                    "ALTER TABLE meal_plan ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 0"
                ))
                db.session.commit()
                print("✓ meal_plan.is_active added")
            # Backfill: athletes with meal plans but none marked active -> activate the most recent one
            from app.models import MealPlan
            from sqlalchemy import distinct
            athlete_ids_with_plans = [row[0] for row in db.session.query(distinct(MealPlan.athlete_id)).all()]
            for aid in athlete_ids_with_plans:
                if not MealPlan.query.filter_by(athlete_id=aid, is_active=True).first():
                    latest = MealPlan.query.filter_by(athlete_id=aid).order_by(MealPlan.created_at.desc()).first()
                    if latest:
                        latest.is_active = True
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ meal_plan.is_active alter skipped: {e}")

        # Roles / coach-athlete association / subscription
        try:
            from sqlalchemy import inspect as sa_inspect6
            inspector6 = sa_inspect6(db.engine)
            user_cols = {col['name'] for col in inspector6.get_columns('user')}
            if 'coach_id' not in user_cols:
                db.session.execute(db.text(
                    "ALTER TABLE `user` ADD COLUMN coach_id INT NULL"
                ))
            if 'coach_associated_at' not in user_cols:
                db.session.execute(db.text(
                    "ALTER TABLE `user` ADD COLUMN coach_associated_at DATETIME NULL"
                ))
            if 'subscription_tier' not in user_cols:
                db.session.execute(db.text(
                    "ALTER TABLE `user` ADD COLUMN subscription_tier INT NOT NULL DEFAULT 0"
                ))
            db.session.commit()
            print("✓ user coach_id / subscription_tier OK")
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ user association alter skipped: {e}")

        # Créer / migrer les comptes admin & coach
        from app.models import User
        admin_legacy = User.query.filter_by(username='admin').first()
        if not admin_legacy:
            print("Creating default coach user 'admin'...")
            admin_legacy = User(username='admin', role='coach', subscription_tier=3, display_name='Coach')
            admin_legacy.set_password(os.environ.get('ADMIN_PASSWORD', 'admin123'))
            db.session.add(admin_legacy)
            db.session.commit()
            print("✓ Coach user 'admin' created")
        else:
            # Compte historique 'admin' = coach (plus le rôle admin plateforme)
            if admin_legacy.role != 'coach':
                admin_legacy.role = 'coach'
            if admin_legacy.subscription_tier is None:
                admin_legacy.subscription_tier = 3
            elif int(admin_legacy.subscription_tier or 0) == 0:
                # Premier déploiement : donner un tier large au coach historique
                admin_legacy.subscription_tier = 3
            db.session.commit()

        # Backfill : athlètes sans coach → rattachés au coach historique 'admin'
        try:
            orphan_athletes = User.query.filter_by(role='athlete', coach_id=None).all()
            if orphan_athletes and admin_legacy:
                for a in orphan_athletes:
                    a.coach_id = admin_legacy.id
                    if not a.coach_associated_at:
                        a.coach_associated_at = datetime.utcnow()
                db.session.commit()
                print(f"✓ {len(orphan_athletes)} athlete(s) rattachés au coach admin")
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ athlete backfill skipped: {e}")

        superadmin = User.query.filter_by(username='superadmin').first()
        if not superadmin:
            print("Creating platform admin 'superadmin'...")
            superadmin = User(
                username='superadmin', role='admin', display_name='Admin',
                subscription_tier=0,
            )
            superadmin.set_password(os.environ.get('SUPERADMIN_PASSWORD', 'superadmin123'))
            db.session.add(superadmin)
            db.session.commit()
            print("✓ superadmin created (change password in prod)")
        
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

    # Mobile JWT API (Expo Android / iOS / Web)
    from app.mobile_api import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    @app.get('/health')
    def health():
        return {'status': 'ok', 'service': 'dru', 'mobile_api': True}

    # Jinja filter: formate "Rest: 0.5min" → "Repos: 0:30"
    import re, math
    def _dec_min_to_mmss(dec_str):
        try:
            val = float(dec_str)
            m = int(math.floor(val))
            s = round((val - m) * 60)
            return f"{m}:{str(s).zfill(2)}"
        except (ValueError, TypeError):
            return dec_str

    @app.template_filter('format_rest')
    def format_rest_filter(text):
        """Remplace 'Rest: 1.5min' par 'Repos: 1:30' dans une description de série"""
        if not text:
            return text
        def replacer(m):
            return f"Repos: {_dec_min_to_mmss(m.group(1))}"
        return re.sub(r'Rest:\s*([\d.]+)\s*min', replacer, text, flags=re.IGNORECASE)

    return app
