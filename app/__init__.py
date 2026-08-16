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
            if 'email' not in user_cols:
                db.session.execute(db.text(
                    "ALTER TABLE `user` ADD COLUMN email VARCHAR(255) NULL"
                ))
            if 'independent_module' not in user_cols:
                db.session.execute(db.text(
                    "ALTER TABLE `user` ADD COLUMN independent_module TINYINT(1) NOT NULL DEFAULT 0"
                ))
            # Username élargi pour stocker un email éventuel
            try:
                db.session.execute(db.text(
                    "ALTER TABLE `user` MODIFY COLUMN username VARCHAR(255) NOT NULL"
                ))
            except Exception:
                pass
            try:
                db.session.execute(db.text(
                    "CREATE UNIQUE INDEX uq_user_email ON `user` (email)"
                ))
            except Exception:
                pass
            db.session.commit()
            print("✓ user coach_id / subscription_tier / email / independent_module OK")
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ user association alter skipped: {e}")

        try:
            from sqlalchemy import inspect as sa_inspect_bank
            inspector_bank = sa_inspect_bank(db.engine)
            if 'exercise' in inspector_bank.get_table_names():
                ecols = {c['name'] for c in inspector_bank.get_columns('exercise')}
                if 'owner_id' not in ecols:
                    db.session.execute(db.text("ALTER TABLE exercise ADD COLUMN owner_id INT NULL"))
                    db.session.commit()
                    print("✓ exercise.owner_id OK")
            if 'food' in inspector_bank.get_table_names():
                fcols = {c['name'] for c in inspector_bank.get_columns('food')}
                if 'owner_id' not in fcols:
                    db.session.execute(db.text("ALTER TABLE food ADD COLUMN owner_id INT NULL"))
                    db.session.commit()
                    print("✓ food.owner_id OK")
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ bank owner_id alter skipped: {e}")

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

        # Email Paul
        try:
            paul_email = 'paul.gilliard.8@gmail.com'
            paul = (
                User.query.filter(db.func.lower(User.email) == paul_email).first()
                or User.query.filter(User.username.ilike('paul%')).first()
                or User.query.filter(User.display_name.ilike('%paul%')).first()
            )
            if paul:
                conflict = User.query.filter(
                    db.func.lower(User.email) == paul_email, User.id != paul.id,
                ).first()
                if not conflict:
                    paul.email = paul_email
                    db.session.commit()
                    print(f"✓ email Paul → {paul_email} (user #{paul.id})")
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Paul email skipped: {e}")

        # Compte admin plateforme : Superadmin
        platform_admin_password = os.environ.get('SUPERADMIN_PASSWORD', '14785commePAUL!')
        try:
            platform_admin = (
                User.query.filter_by(username='Superadmin').first()
                or User.query.filter(db.func.lower(User.username) == 'superadmin').first()
            )
            if platform_admin:
                platform_admin.username = 'Superadmin'
                platform_admin.display_name = 'Superadmin'
                platform_admin.role = 'admin'
                platform_admin.set_password(platform_admin_password)
                db.session.commit()
                print("✓ Superadmin mis à jour")
            else:
                platform_admin = User(
                    username='Superadmin', role='admin', display_name='Superadmin',
                    subscription_tier=0,
                )
                platform_admin.set_password(platform_admin_password)
                db.session.add(platform_admin)
                db.session.commit()
                print("✓ Superadmin créé")
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Superadmin skipped: {e}")
        
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
        return {'status': 'ok', 'service': 'farmness', 'mobile_api': True}

    @app.get('/privacy')
    def privacy_policy():
        """Politique de confidentialité — URL obligatoire Play Store / App Store."""
        from flask import Response
        html = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Farmness — Politique de confidentialité</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1.25rem; line-height: 1.55; color: #111; }
    h1, h2 { line-height: 1.25; }
    h1 { font-size: 1.6rem; }
    h2 { font-size: 1.15rem; margin-top: 1.75rem; }
    .muted { color: #555; font-size: 0.95rem; }
  </style>
</head>
<body>
  <h1>Politique de confidentialité — Farmness</h1>
  <p class="muted">Dernière mise à jour : 15 août 2026 · Éditeur : Paul Gilliard · Contact : paul.gilliard.8@gmail.com</p>

  <h2>1. Qui sommes-nous</h2>
  <p>Farmness est une application mobile de suivi sportif (programmes, journal, nutrition, performances) destinée aux athlètes et à leurs coachs.</p>

  <h2>2. Données collectées</h2>
  <ul>
    <li><strong>Compte</strong> : identifiant / e-mail, mot de passe (hashé), nom d’affichage, rôle (athlète, coach, admin).</li>
    <li><strong>Données sportives</strong> : programmes, séances, performances, objectifs, disponibilités.</li>
    <li><strong>Journal / santé saisis</strong> : poids, sommeil, pas, hydratation, macros, sensations (énergie, stress, faim), notes.</li>
    <li><strong>Nutrition</strong> : plans alimentaires et aliments associés.</li>
    <li><strong>Technique</strong> : jeton d’authentification stocké localement sur l’appareil, logs serveur usuels.</li>
  </ul>

  <h2>3. Health Connect (Android uniquement)</h2>
  <p>Avec ton accord explicite, Farmness peut lire via Health Connect : pas, sommeil et nutrition. Le poids n’est jamais synchronisé automatiquement. Tu peux révoquer ces permissions à tout moment dans Health Connect / les réglages Android.</p>

  <h2>4. Finalités</h2>
  <p>Fournir le service (entraînement, suivi coach/athlète), améliorer la fiabilité de l’app, et assurer la sécurité des comptes. Pas de vente de données personnelles à des tiers publicitaires.</p>

  <h2>5. Base légale</h2>
  <p>Exécution du contrat (fourniture du service), consentement (Health Connect), et intérêt légitime (sécurité / prévention d’abus).</p>

  <h2>6. Hébergement &amp; conservation</h2>
  <p>Les données applicatives sont hébergées sur l’infrastructure cloud utilisée pour l’API Farmness (Railway). Elles sont conservées tant que le compte existe, sauf demande de suppression.</p>

  <h2>7. Partage</h2>
  <p>Un athlète lié à un coach partage avec ce coach les données nécessaires au coaching (programmes, journal, perfs, etc.). Pas d’autre partage commercial.</p>

  <h2>8. Tes droits</h2>
  <p>Tu peux demander l’accès, la rectification ou la suppression de ton compte / données en écrivant à <a href="mailto:paul.gilliard.8@gmail.com">paul.gilliard.8@gmail.com</a>. Tu peux aussi te désinscrire / te déconnecter dans l’app.</p>

  <h2>9. Sécurité</h2>
  <p>Authentification JWT, mots de passe hashés, communications HTTPS vers l’API. Aucune sécurité n’est absolue ; signale tout incident suspect au contact ci-dessus.</p>

  <h2>10. Mineurs</h2>
  <p>L’app s’adresse à un public adulte ou sous supervision d’un coach / parent. Pas destinée aux enfants de moins de 13 ans.</p>

  <h2>11. Modifications</h2>
  <p>Cette politique peut évoluer. La date en tête de page sera mise à jour. En cas de changement important, une information pourra être affichée dans l’app.</p>
</body>
</html>"""
        return Response(html, mimetype='text/html; charset=utf-8')

    @app.get('/support')
    def support_page():
        from flask import Response
        html = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Farmness — Support</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1.25rem; line-height: 1.55; }
  </style>
</head>
<body>
  <h1>Support Farmness</h1>
  <p>Pour toute question, bug ou demande liée à ton compte :</p>
  <p><a href="mailto:paul.gilliard.8@gmail.com">paul.gilliard.8@gmail.com</a></p>
  <p><a href="/privacy">Politique de confidentialité</a></p>
</body>
</html>"""
        return Response(html, mimetype='text/html; charset=utf-8')

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
