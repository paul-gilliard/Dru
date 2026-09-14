"""Journal léger des tentatives suspectes (admin oversight)."""
from __future__ import annotations

import json
from typing import Any

from flask import has_request_context, request
from sqlalchemy.orm import Session


def log_security_event(
    event_type: str,
    *,
    severity: str = 'info',
    detail: dict[str, Any] | None = None,
    user_id: int | None = None,
    path: str | None = None,
    ip: str | None = None,
) -> None:
    """Best-effort insert via session isolée — ne touche pas la transaction métier."""
    try:
        from app import db
        from app.auth_security import client_ip
        from app.models import SecurityEvent

        if has_request_context():
            if path is None:
                path = request.path
            if ip is None:
                ip = client_ip()
            if user_id is None and getattr(request, 'current_user', None) is not None:
                user_id = request.current_user.id

        row = SecurityEvent(
            event_type=(event_type or 'unknown')[:64],
            severity=(severity or 'info')[:16],
            user_id=user_id,
            ip=(ip or 'unknown')[:64],
            path=(path or '')[:255] or None,
            detail_json=json.dumps(detail or {}, ensure_ascii=False)[:4000],
        )
        # Session séparée : évite commit/rollback collatéral sur la req en cours.
        with Session(db.engine) as session:
            session.add(row)
            session.commit()
    except Exception:
        pass
