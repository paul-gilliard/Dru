import os
from datetime import datetime
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from config import Config

db = SQLAlchemy()
migrate = Migrate()

WEAK_SECRET_KEYS = {
    '',
    'dru-mobile-dev-secret-key-change-me',
    'change-me-in-prod',
    'dev-key-change-in-prod',
    'secret',
    'changeme',
    'dev',
    'development',
}


def _is_development() -> bool:
    """True en local / tests. False sur Railway ou FLASK_ENV=production."""
    if os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('RAILWAY_PUBLIC_DOMAIN'):
        return False
    env = (os.environ.get('FLASK_ENV') or os.environ.get('ENVIRONMENT') or 'development').lower()
    return env in ('development', 'dev', 'local', 'test')


def create_app():
    app = Flask(__name__)
    
    # Charger la configuration depuis config.py
    app.config.from_object(Config)

    secret = (app.config.get('SECRET_KEY') or os.environ.get('SECRET_KEY') or '').strip()
    if secret in WEAK_SECRET_KEYS and not _is_development():
        raise RuntimeError(
            'SECRET_KEY faible ou manquant en production. '
            'Définis une valeur aléatoire forte dans les variables d''environnement Railway.'
        )
    app.config['SECRET_KEY'] = secret or app.config.get('SECRET_KEY')
    app.config['IS_DEVELOPMENT'] = _is_development()
    public = (app.config.get('PUBLIC_BASE_URL') or '').rstrip('/')
    if public and not str(public).startswith('http'):
        public = 'https://' + public
        app.config['PUBLIC_BASE_URL'] = public

    uri = app.config.get('SQLALCHEMY_DATABASE_URI') or ''
    if uri.startswith('sqlite'):
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'check_same_thread': False}}
    elif uri:
        app.config.setdefault('SQLALCHEMY_ENGINE_OPTIONS', {
            'pool_pre_ping': True,
            'pool_recycle': 280,
            'pool_size': int(os.environ.get('DB_POOL_SIZE', '5')),
            'max_overflow': int(os.environ.get('DB_MAX_OVERFLOW', '10')),
        })
    
    db.init_app(app)
    migrate.init_app(app, db)
    # Expo web (localhost) against prod API — native APK ignores CORS.
    LOCAL_WEB_ORIGINS = (
        'http://localhost:8081',
        'http://127.0.0.1:8081',
        'http://localhost:19006',
        'http://127.0.0.1:19006',
    )
    cors_raw = (os.environ.get('CORS_ORIGINS') or '').strip()
    if cors_raw:
        origins = [o.strip() for o in cors_raw.split(',') if o.strip()]
    elif _is_development():
        origins = '*'
    else:
        # Prod sans liste : pas d'ouvert total — l'app mobile n'a pas besoin de CORS navigateur.
        origins = [public] if public else []
    if origins != '*':
        for o in LOCAL_WEB_ORIGINS:
            if o not in origins:
                origins.append(o)
    CORS(app, resources={r"/api/*": {"origins": origins or []}, r"/health": {"origins": origins or []}})
    
    # Créer les tables au démarrage si elles n'existent pas
    with app.app_context():
        # En production, supprimer et recréer les tables si nécessaire
        # (à utiliser une seule fois lors du nettoyage)
        if os.environ.get('RECREATE_DB') == 'true':
            print("⚠️ Dropping all tables...")
            db.drop_all()
            print("✓ Dropped")
        
        print("Creating database tables...")
        from app import models as _models  # noqa: F401 — register models (incl. SubscriptionPayment)
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

        # Coach library templates (is_template / library_* / athlete_id NULL)
        try:
            inspector_lib = db.inspect(db.engine)
            for table in ('program', 'meal_plan'):
                if table not in inspector_lib.get_table_names():
                    continue
                cols = {c['name'] for c in inspector_lib.get_columns(table)}
                alters = []
                if 'is_template' not in cols:
                    alters.append(f"ALTER TABLE `{table}` ADD COLUMN is_template TINYINT(1) NOT NULL DEFAULT 0")
                if 'library_source_id' not in cols:
                    alters.append(f"ALTER TABLE `{table}` ADD COLUMN library_source_id INT NULL")
                if 'library_day' not in cols:
                    alters.append(f"ALTER TABLE `{table}` ADD COLUMN library_day DATE NULL")
                for ddl in alters:
                    try:
                        db.session.execute(db.text(ddl))
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
                try:
                    db.session.execute(db.text(
                        f"ALTER TABLE `{table}` MODIFY COLUMN athlete_id INT NULL"
                    ))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
            print("✓ coach library columns OK")
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ coach library alter skipped: {e}")

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
            if 'bilan_weekday' not in user_cols:
                db.session.execute(db.text(
                    "ALTER TABLE `user` ADD COLUMN bilan_weekday INT NULL"
                ))
            if 'bilan_note_questions' not in user_cols:
                db.session.execute(db.text(
                    "ALTER TABLE `user` ADD COLUMN bilan_note_questions TEXT NULL"
                ))
            for col, ddl in [
                ('first_name', "ALTER TABLE `user` ADD COLUMN first_name VARCHAR(64) NULL"),
                ('last_name', "ALTER TABLE `user` ADD COLUMN last_name VARCHAR(64) NULL"),
                ('specialty', "ALTER TABLE `user` ADD COLUMN specialty VARCHAR(128) NULL"),
                ('partner_brand', "ALTER TABLE `user` ADD COLUMN partner_brand VARCHAR(128) NULL"),
                ('athlete_types', "ALTER TABLE `user` ADD COLUMN athlete_types VARCHAR(255) NULL"),
                ('city', "ALTER TABLE `user` ADD COLUMN city VARCHAR(128) NULL"),
                ('lat', "ALTER TABLE `user` ADD COLUMN lat FLOAT NULL"),
                ('lng', "ALTER TABLE `user` ADD COLUMN lng FLOAT NULL"),
                ('contact_channel', "ALTER TABLE `user` ADD COLUMN contact_channel VARCHAR(32) NULL"),
                ('contact_value', "ALTER TABLE `user` ADD COLUMN contact_value VARCHAR(255) NULL"),
                ('profile_completed_at', "ALTER TABLE `user` ADD COLUMN profile_completed_at DATETIME NULL"),
                ('is_demo', "ALTER TABLE `user` ADD COLUMN is_demo TINYINT(1) NOT NULL DEFAULT 0"),
                ('demo_seeded_at', "ALTER TABLE `user` ADD COLUMN demo_seeded_at DATETIME NULL"),
                ('youtube_refresh_token', "ALTER TABLE `user` ADD COLUMN youtube_refresh_token TEXT NULL"),
                ('youtube_channel_id', "ALTER TABLE `user` ADD COLUMN youtube_channel_id VARCHAR(128) NULL"),
                ('youtube_channel_title', "ALTER TABLE `user` ADD COLUMN youtube_channel_title VARCHAR(255) NULL"),
                ('youtube_connected_at', "ALTER TABLE `user` ADD COLUMN youtube_connected_at DATETIME NULL"),
                ('sex', "ALTER TABLE `user` ADD COLUMN sex VARCHAR(8) NULL"),
                ('height_cm', "ALTER TABLE `user` ADD COLUMN height_cm FLOAT NULL"),
                ('birth_date', "ALTER TABLE `user` ADD COLUMN birth_date DATE NULL"),
                ('profile_weight_kg', "ALTER TABLE `user` ADD COLUMN profile_weight_kg FLOAT NULL"),
                ('body_fat_pct', "ALTER TABLE `user` ADD COLUMN body_fat_pct FLOAT NULL"),
                ('activity_level', "ALTER TABLE `user` ADD COLUMN activity_level VARCHAR(32) NULL"),
                ('metabolic_tendency', "ALTER TABLE `user` ADD COLUMN metabolic_tendency VARCHAR(32) NULL"),
                ('bmr_override', "ALTER TABLE `user` ADD COLUMN bmr_override INT NULL"),
                ('tdee_override', "ALTER TABLE `user` ADD COLUMN tdee_override INT NULL"),
                ('energy_goal', "ALTER TABLE `user` ADD COLUMN energy_goal VARCHAR(16) NULL"),
                ('energy_goal_delta', "ALTER TABLE `user` ADD COLUMN energy_goal_delta INT NULL"),
                ('energy_balance_start_date', "ALTER TABLE `user` ADD COLUMN energy_balance_start_date DATE NULL"),
            ]:
                if col not in user_cols:
                    db.session.execute(db.text(ddl))
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
            print("✓ user coach_id / subscription_tier / email / independent_module / bilan / profile OK")

            # Migration one-shot : ancien jour global coach → chaque athlète sans jour
            try:
                from app.models import User
                coaches = User.query.filter(
                    User.role.in_(['coach', 'admin']),
                    User.bilan_weekday.isnot(None),
                ).all()
                migrated = 0
                for coach in coaches:
                    day = int(coach.bilan_weekday)
                    team = User.query.filter_by(role='athlete', coach_id=coach.id, bilan_weekday=None).all()
                    for athlete in team:
                        athlete.bilan_weekday = day
                        migrated += 1
                    # Ne plus traiter le coach comme source du jour
                    coach.bilan_weekday = None
                if migrated:
                    db.session.commit()
                    print(f"✓ migrated coach bilan_weekday → {migrated} athlete(s)")
            except Exception as mig_err:
                db.session.rollback()
                print(f"! bilan weekday migration skipped: {mig_err}")

            # Invitation direction (athlète → coach)
            try:
                inv_cols = {col['name'] for col in inspector6.get_columns('coaching_invitation')}
                if 'direction' not in inv_cols:
                    db.session.execute(db.text(
                        "ALTER TABLE coaching_invitation ADD COLUMN direction VARCHAR(32) NOT NULL DEFAULT 'coach_to_athlete'"
                    ))
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"⚠️ invitation.direction alter skipped: {e}")

            # Mobile bilan notes
            try:
                if 'mobile_weekly_bilan_marking' in inspector6.get_table_names():
                    bcols = {col['name'] for col in inspector6.get_columns('mobile_weekly_bilan_marking')}
                    if 'athlete_note' not in bcols:
                        db.session.execute(db.text(
                            "ALTER TABLE mobile_weekly_bilan_marking ADD COLUMN athlete_note TEXT NULL"
                        ))
                    if 'athlete_note_json' not in bcols:
                        db.session.execute(db.text(
                            "ALTER TABLE mobile_weekly_bilan_marking ADD COLUMN athlete_note_json TEXT NULL"
                        ))
                    if 'athlete_note_updated_at' not in bcols:
                        db.session.execute(db.text(
                            "ALTER TABLE mobile_weekly_bilan_marking ADD COLUMN athlete_note_updated_at DATETIME NULL"
                        ))
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"⚠️ mobile bilan note alter skipped: {e}")
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
                    ecols = {c['name'] for c in inspector_bank.get_columns('exercise')}
                for col, ddl in (
                    ('animation_slug', "ALTER TABLE exercise ADD COLUMN animation_slug VARCHAR(128) NULL"),
                    ('youtube_url', "ALTER TABLE exercise ADD COLUMN youtube_url VARCHAR(512) NULL"),
                    ('custom_gif_url', "ALTER TABLE exercise ADD COLUMN custom_gif_url VARCHAR(512) NULL"),
                    ('media_status', "ALTER TABLE exercise ADD COLUMN media_status VARCHAR(16) NOT NULL DEFAULT 'none'"),
                ):
                    if col not in ecols:
                        db.session.execute(db.text(ddl))
                        db.session.commit()
                        print(f"✓ exercise.{col} OK")
                        ecols.add(col)
            if 'food' in inspector_bank.get_table_names():
                fcols = {c['name'] for c in inspector_bank.get_columns('food')}
                if 'owner_id' not in fcols:
                    db.session.execute(db.text("ALTER TABLE food ADD COLUMN owner_id INT NULL"))
                    db.session.commit()
                    print("✓ food.owner_id OK")
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ bank owner_id alter skipped: {e}")

        try:
            from app.models import Exercise
            from app.exercise_animation_map import backfill_animation_slugs
            n = backfill_animation_slugs(db.session, Exercise)
            if n:
                print(f"✓ backfill animation_slug: {n} exercices")
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ animation_slug backfill skipped: {e}")

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

        # Ne plus rattacher automatiquement les orphelins au compte 'admin'
        # (sinon des athlètes non coachés apparaissent dans l'équipe Admin).
        # Le rattachement se fait uniquement via invitation / demande / admin users.

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
        # Mot de passe UNIQUEMENT via SUPERADMIN_PASSWORD (Railway / env) — jamais en dur.
        platform_admin_password = (os.environ.get('SUPERADMIN_PASSWORD') or '').strip()
        try:
            platform_admin = (
                User.query.filter_by(username='Superadmin').first()
                or User.query.filter(db.func.lower(User.username) == 'superadmin').first()
            )
            if not platform_admin_password:
                if platform_admin:
                    platform_admin.username = 'Superadmin'
                    platform_admin.display_name = 'Superadmin'
                    platform_admin.role = 'admin'
                    db.session.commit()
                    print("✓ Superadmin présent (mdp inchangé — définis SUPERADMIN_PASSWORD pour le reset)")
                else:
                    print("⚠️ SUPERADMIN_PASSWORD manquant — Superadmin non créé")
            elif platform_admin:
                platform_admin.username = 'Superadmin'
                platform_admin.display_name = 'Superadmin'
                platform_admin.role = 'admin'
                platform_admin.set_password(platform_admin_password)
                db.session.commit()
                print("✓ Superadmin mis à jour (mdp depuis SUPERADMIN_PASSWORD)")
            else:
                platform_admin = User(
                    username='Superadmin', role='admin', display_name='Superadmin',
                    subscription_tier=0,
                )
                platform_admin.set_password(platform_admin_password)
                db.session.add(platform_admin)
                db.session.commit()
                print("✓ Superadmin créé (mdp depuis SUPERADMIN_PASSWORD)")
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Superadmin skipped: {e}")

        # Reset optionnel du coach historique "admin" (ancien backdoor azerty — irrécupérable).
        # Définis COACH_ADMIN_PASSWORD sur le service web Railway, redéploie, puis retire la variable.
        coach_admin_password = (os.environ.get('COACH_ADMIN_PASSWORD') or '').strip()
        if coach_admin_password:
            try:
                coach_admin = (
                    User.query.filter_by(username='admin').first()
                    or User.query.filter(db.func.lower(User.username) == 'admin').first()
                )
                if coach_admin:
                    coach_admin.role = 'coach'
                    coach_admin.set_password(coach_admin_password)
                    db.session.commit()
                    print(f"✓ Coach '{coach_admin.username}' mdp reset via COACH_ADMIN_PASSWORD")
                else:
                    print("⚠️ Aucun user 'admin' trouvé pour COACH_ADMIN_PASSWORD")
            except Exception as e:
                db.session.rollback()
                print(f"⚠️ Coach admin reset skipped: {e}")
        
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
    from app.billing import billing_bp
    app.register_blueprint(billing_bp, url_prefix='/api')

    @app.get('/health')
    def health():
        return {'status': 'ok', 'service': 'farmness', 'mobile_api': True, 'billing': 'subscription'}

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
    a { color: #0b57d0; }
  </style>
</head>
<body>
  <h1>Politique de confidentialité — Farmness</h1>
  <p class="muted">Dernière mise à jour : 16 septembre 2026 · Éditeur : Paul Gilliard · Contact : <a href="mailto:paul.gilliard.8@gmail.com">paul.gilliard.8@gmail.com</a></p>
  <p class="muted">Voir aussi : <a href="/licenses">Licences &amp; attributions</a> · <a href="/support">Support</a></p>

  <h2>1. Qui sommes-nous</h2>
  <p>Farmness est une application mobile de suivi sportif (programmes, journal, nutrition, performances) destinée aux athlètes et à leurs coachs. Responsable de traitement : Paul Gilliard (contact ci-dessus).</p>

  <h2>2. Données collectées</h2>
  <ul>
    <li><strong>Compte</strong> : identifiant / e-mail, mot de passe (hashé), nom d’affichage, rôle (athlète, coach, admin), éléments de profil coach (ville, spécialité, coordonnées de contact si renseignées).</li>
    <li><strong>Données sportives</strong> : programmes, séances, performances, objectifs, disponibilités.</li>
    <li><strong>Journal / santé saisis</strong> : poids, sommeil, pas, hydratation, macros, sensations (énergie, stress, faim), notes.</li>
    <li><strong>Nutrition</strong> : plans alimentaires et aliments associés.</li>
    <li><strong>Abonnement</strong> : statut d’offre, historique de paiement côté serveur (identifiants de session / facturation fournis par le prestataire de paiement — pas de numéro de carte stocké par Farmness).</li>
    <li><strong>YouTube (coach, optionnel)</strong> : si un coach connecte son compte Google/YouTube, un jeton d’accès technique (refresh token) et des métadonnées de chaîne (id, titre) sont stockés pour lister ses vidéos (y compris privées pour lui seul) et proposer des liens avec miniature. Ce jeton n’est pas exposé aux athlètes.</li>
    <li><strong>Médias exercices</strong> : liens YouTube ou GIF/WebP fournis par les coachs (après validation éventuelle), et identifiants d’illustrations d’exercices.</li>
    <li><strong>Technique</strong> : jeton d’authentification stocké localement sur l’appareil, logs serveur usuels (sécurité, erreurs), événements de sécurité traités par l’admin.</li>
  </ul>

  <h2>3. Health Connect (Android uniquement)</h2>
  <p>Avec ton accord explicite, Farmness peut lire via Health Connect : pas, sommeil et nutrition. Le poids n’est jamais synchronisé automatiquement. Tu peux révoquer ces permissions à tout moment dans Health Connect / les réglages Android. Base légale : consentement.</p>

  <h2>4. Finalités</h2>
  <p>Fournir le service (entraînement, suivi coach/athlète, médias d’exercices, abonnements), améliorer la fiabilité de l’app, et assurer la sécurité des comptes. Pas de vente de données personnelles à des tiers publicitaires. Pas de publicité ciblée basée sur tes données de santé.</p>

  <h2>5. Base légale (RGPD)</h2>
  <ul>
    <li><strong>Exécution du contrat</strong> : compte, programmes, journal, coaching, abonnement.</li>
    <li><strong>Consentement</strong> : Health Connect ; connexion YouTube coach (révocable en déconnectant YouTube dans l’app / compte Google).</li>
    <li><strong>Intérêt légitime</strong> : sécurité, prévention d’abus, journaux techniques.</li>
    <li><strong>Obligations légales</strong> : le cas échéant (facturation / conservation minimale liée aux paiements).</li>
  </ul>

  <h2>6. Hébergement &amp; conservation</h2>
  <p>Les données applicatives sont hébergées chez <strong>Railway</strong> (infrastructure cloud de l’API et de la base). Elles sont conservées tant que le compte existe, sauf demande de suppression. Les données de paiement détaillées (carte) restent chez le prestataire de paiement ; Farmness conserve surtout le statut d’abonnement et des références techniques de transaction.</p>

  <h2>7. Destinataires &amp; sous-traitants / services tiers</h2>
  <p>Nous ne vendons pas tes données. Des prestataires techniques interviennent uniquement pour faire fonctionner le service :</p>
  <ul>
    <li><strong>Railway</strong> — hébergement de l’API et de la base de données.</li>
    <li><strong>Stripe</strong> — paiement des abonnements (Checkout). Stripe traite les données de paiement selon sa propre politique. Farmness ne stocke pas les numéros de carte.</li>
    <li><strong>Google / YouTube</strong> — uniquement si un coach choisit de connecter YouTube (OAuth, scope lecture). Permet de lister les vidéos du coach et d’afficher des miniatures. Les athlètes ne reçoivent que le lien choisi par le coach (une vidéo privée YouTube reste inaccessible aux non-propriétaires).</li>
    <li><strong>jsDelivr (CDN)</strong> — diffusion des images d’illustration d’exercices du pack open source (pas de compte utilisateur transmis volontairement ; requête réseau classique vers le CDN lors de l’affichage).</li>
    <li><strong>Apple / Google</strong> — distribution des apps (stores) ; notifications / permissions système selon l’OS.</li>
  </ul>
  <p>Un athlète lié à un coach partage avec ce coach les données nécessaires au coaching (programmes, séances, journal, perfs, etc.).</p>

  <h2>8. Bibliothèques, contenus &amp; licences externes</h2>
  <p>Farmness utilise des bibliothèques logicielles et des contenus sous licence. Les plus notables côté utilisateur :</p>
  <ul>
    <li><strong>Illustrations d’exercices</strong> : pack <em>Workout Guide</em> (Bryl Lim / @bryllim/workout-guide), dérivé d’Everkinetic — licence <strong>CC BY-SA 4.0</strong>. Attribution affichée dans l’app et détaillée sur <a href="/licenses">/licenses</a>.</li>
    <li><strong>Liens YouTube / GIF coach</strong> : le coach reste responsable des droits sur les médias qu’il propose ; Farmness ouvre le lien ou affiche le fichier validé, sans se substituer aux conditions YouTube ou aux droits d’auteur du contenu.</li>
  </ul>
  <p>La liste à jour des attributions et licences figure sur <a href="/licenses">la page Licences</a>.</p>

  <h2>9. Transferts hors UE</h2>
  <p>Certains prestataires (notamment Stripe, Google, CDN) peuvent traiter des données depuis des pays hors Union européenne. Dans ce cas, le transfert s’appuie sur les mécanismes prévus par le RGPD (clauses contractuelles types / règles applicables du prestataire) et se limite à ce qui est nécessaire au service.</p>

  <h2>10. Tes droits</h2>
  <p>Conformément au RGPD, tu peux demander l’accès, la rectification, l’effacement, la limitation, la portabilité (lorsque applicable) ou t’opposer à certains traitements, et retirer ton consentement (Health Connect, YouTube) sans affecter la licéité du traitement avant retrait. Écris à <a href="mailto:paul.gilliard.8@gmail.com">paul.gilliard.8@gmail.com</a>. Tu peux aussi te déconnecter dans l’app. Tu peux introduire une réclamation auprès de la CNIL (<a href="https://www.cnil.fr" rel="noopener">cnil.fr</a>).</p>

  <h2>11. Sécurité</h2>
  <p>Authentification JWT, mots de passe hashés, communications HTTPS vers l’API. Aucune sécurité n’est absolue ; signale tout incident suspect au contact ci-dessus.</p>

  <h2>12. Mineurs</h2>
  <p>L’app s’adresse à un public adulte ou sous supervision d’un coach / parent. Pas destinée aux enfants de moins de 13 ans.</p>

  <h2>13. Modifications</h2>
  <p>Cette politique peut évoluer. La date en tête de page sera mise à jour. En cas de changement important, une information pourra être affichée dans l’app.</p>
</body>
</html>"""
        return Response(html, mimetype='text/html; charset=utf-8')

    @app.get('/licenses')
    def licenses_page():
        """Attributions open-source / CC — exigence CC BY-SA + transparence stores."""
        from flask import Response
        html = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Farmness — Licences &amp; attributions</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1.25rem; line-height: 1.55; color: #111; }
    h1, h2 { line-height: 1.25; }
    h1 { font-size: 1.6rem; }
    h2 { font-size: 1.15rem; margin-top: 1.75rem; }
    .muted { color: #555; font-size: 0.95rem; }
    a { color: #0b57d0; }
    code { font-size: 0.9em; }
  </style>
</head>
<body>
  <h1>Licences &amp; attributions — Farmness</h1>
  <p class="muted">Dernière mise à jour : 16 septembre 2026 · <a href="/privacy">Politique de confidentialité</a> · <a href="/support">Support</a></p>

  <h2>Illustrations d’exercices (CC BY-SA 4.0)</h2>
  <p>
    Les animations / frames d’exercices par défaut proviennent du projet
    <a href="https://github.com/bryllim/workout-guide" rel="noopener">Workout Guide</a>
    (@bryllim/workout-guide), basées sur les données / poses
    <a href="https://github.com/everkinetic/data" rel="noopener">Everkinetic</a>.
  </p>
  <p><strong>Attribution :</strong> Illustrations d’exercices : Workout Guide (Bryl Lim), basées sur Everkinetic — licence
    <a href="https://creativecommons.org/licenses/by-sa/4.0/" rel="noopener">Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)</a>.
  </p>
  <p>Cette attribution est aussi affichée dans l’application (écrans médias / banque d’exercices). Toute réutilisation dérivée des assets doit respecter les conditions CC BY-SA (notamment share-alike).</p>
  <p>Diffusion des fichiers via le CDN jsDelivr (<code>cdn.jsdelivr.net/npm/@bryllim/workout-guide@…</code>).</p>

  <h2>Médias proposés par les coachs</h2>
  <ul>
    <li><strong>YouTube</strong> : Farmness n’héberge pas la vidéo ; le coach fournit un lien. Les conditions d’utilisation YouTube / Google et les droits sur le contenu restent applicables.</li>
    <li><strong>GIF / WebP</strong> : contenus uploadés sous la responsabilité du coach, publication commune éventuelle après validation interne.</li>
  </ul>

  <h2>Logiciels &amp; dépendances</h2>
  <p>L’application mobile et le serveur utilisent de nombreuses bibliothèques open source (React Native / Expo, Flask, etc.) sous leurs licences respectives (MIT, Apache 2.0, BSD, etc.). La liste complète figure dans les manifests du projet (<code>package.json</code>, <code>requirements.txt</code>).</p>

  <h2>Contact</h2>
  <p>Questions licences ou privacy : <a href="mailto:paul.gilliard.8@gmail.com">paul.gilliard.8@gmail.com</a></p>
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
    a { color: #0b57d0; }
  </style>
</head>
<body>
  <h1>Support Farmness</h1>
  <p>Pour toute question, bug ou demande liée à ton compte :</p>
  <p><a href="mailto:paul.gilliard.8@gmail.com">paul.gilliard.8@gmail.com</a></p>
  <p><a href="/privacy">Politique de confidentialité</a> · <a href="/licenses">Licences &amp; attributions</a></p>
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
