from app import create_app, db
from app.models import User, Role, create_default_admin

app = create_app()

with app.app_context():
    # si tu as fait les migrations, tu peux commenter db.create_all()
    db.create_all()

    # créer roles
    for name in ('coach', 'athlete'):
        if not Role.query.filter_by(name=name).first():
            db.session.add(Role(name=name))

    # créer admin (login=admin / pass=admin)
    create_default_admin()

    # exemples d'utilisateurs supplémentaires
    if not User.query.filter_by(username='coach1').first():
        u = User(username='coach1', role='coach')
        u.set_password('coachpass')
        db.session.add(u)

    if not User.query.filter_by(username='athlete1').first():
        u = User(username='athlete1', role='athlete')
        u.set_password('athletepass')
        db.session.add(u)

    db.session.commit()
    print('Seed terminé : admin/admin, coach1/coachpass, athlete1/athletepass')