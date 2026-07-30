import jwt
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import request, jsonify, current_app

from app.models import User

TOKEN_TTL_DAYS = 30


def generate_token(user):
    payload = {
        'sub': user.id,
        'role': user.role,
        'exp': datetime.now(timezone.utc) + timedelta(days=TOKEN_TTL_DAYS),
        'iat': datetime.now(timezone.utc),
    }
    return jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')


def decode_token(token):
    return jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])


def get_bearer_token():
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:]
    return None


def _resolve_current_user():
    """Returns (user, error_response) — error_response is None on success."""
    token = get_bearer_token()
    if not token:
        return None, (jsonify({'error': 'Authentification requise'}), 401)
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        return None, (jsonify({'error': 'Session expirée, reconnectez-vous'}), 401)
    except jwt.InvalidTokenError:
        return None, (jsonify({'error': 'Token invalide'}), 401)

    user = User.query.get(payload.get('sub'))
    if not user:
        return None, (jsonify({'error': 'Utilisateur introuvable'}), 401)
    return user, None


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user, error = _resolve_current_user()
        if error:
            return error
        request.current_user = user
        return fn(*args, **kwargs)
    return wrapper


def coach_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user, error = _resolve_current_user()
        if error:
            return error
        if user.role != 'coach':
            return jsonify({'error': 'Réservé au coach'}), 403
        request.current_user = user
        return fn(*args, **kwargs)
    return wrapper

