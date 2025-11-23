"""
Script d'initialisation de la base de données
À exécuter une fois lors du premier déploiement
"""
import os
import sys
from app import create_app, db

def init_db():
    """Initialise la base de données (crée les tables)"""
    app = create_app()
    
    with app.app_context():
        print("Creating database tables...")
        db.create_all()
        print("✓ Database tables created successfully!")
        
        # Optionnel: ajouter un utilisateur admin par défaut
        from app.models import User
        
        # Vérifier si admin existe déjà
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            print("Creating default admin user...")
            admin = User(username='admin', role='coach')
            admin.set_password(os.environ.get('ADMIN_PASSWORD', 'admin123'))
            db.session.add(admin)
            db.session.commit()
            print("✓ Admin user created (username: admin, password: check env vars)")
        else:
            print("✓ Admin user already exists")

if __name__ == '__main__':
    init_db()
