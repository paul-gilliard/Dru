"""Fixtures pytest — SQLite temporaire, app Flask isolée (repo Dru prod)."""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('FLASK_ENV', 'development')
os.environ.setdefault('SECRET_KEY', 'test-secret-key-not-for-prod-32b!!')
os.environ['DATABASE_URL'] = ''  # force non-prod path where possible


@pytest.fixture()
def app(tmp_path, monkeypatch):
    db_path = tmp_path / 'test.db'
    monkeypatch.setenv('FLASK_ENV', 'development')
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key-not-for-prod-32b!!')
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{db_path}')
    monkeypatch.delenv('RAILWAY_ENVIRONMENT', raising=False)
    monkeypatch.delenv('RAILWAY_PUBLIC_DOMAIN', raising=False)

    from app import create_app, db
    application = create_app()
    application.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'SECRET_KEY': 'test-secret-key-not-for-prod-32b!!',
        'STRIPE_SECRET_KEY': 'sk_test_dummy',
        'STRIPE_WEBHOOK_SECRET': '',
        'IS_DEVELOPMENT': True,
        'SQLALCHEMY_ENGINE_OPTIONS': {'connect_args': {'check_same_thread': False}},
    })
    # Re-bind engine to sqlite test DB
    with application.app_context():
        db.session.remove()
        db.engine.dispose()
        application.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
        db.create_all()
        yield application
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def make_user(app):
    from app import db
    from app.models import User

    def _make(*, role='athlete', username=None, email=None, password='password123',
              coach_id=None, subscription_tier=0, is_demo=False, independent_module=False):
        uname = username or f'{role}_{User.query.count() + 1}@test.local'
        mail = email if email is not None else (uname if '@' in uname else f'{uname}@test.local')
        u = User(
            username=uname,
            email=mail,
            role=role,
            display_name=uname.split('@')[0],
            coach_id=coach_id,
            subscription_tier=subscription_tier,
            is_demo=is_demo,
            independent_module=independent_module,
        )
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        db.session.refresh(u)
        return u

    return _make


@pytest.fixture()
def auth_header(app):
    def _header(user, password='password123'):
        from app.mobile_auth import generate_token
        from app.models import User
        with app.app_context():
            uid = int(getattr(user, 'id'))
            fresh = User.query.get(uid)
            token = generate_token(fresh)
        return {'Authorization': f'Bearer {token}'}
    return _header