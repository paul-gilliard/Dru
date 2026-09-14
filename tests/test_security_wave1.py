"""Wave 1 — IDOR, bilan ownership, webhook fail-closed, quota démo."""
from __future__ import annotations

from datetime import date

import pytest


def test_coach_cannot_read_other_coach_program(client, make_user, auth_header):
    coach_a = make_user(role='coach', username='coach_a@test.local', subscription_tier=3)
    coach_b = make_user(role='coach', username='coach_b@test.local', subscription_tier=3)
    athlete_b = make_user(role='athlete', username='ath_b@test.local', coach_id=coach_b.id)

    from app import db
    from app.models import Program
    prog = Program(name='Secret B', athlete_id=athlete_b.id, coach_id=coach_b.id)
    db.session.add(prog)
    db.session.commit()
    prog_id = prog.id

    res = client.get(f'/api/programs/{prog_id}', headers=auth_header(coach_a))
    assert res.status_code == 403


def test_coach_cannot_update_other_athlete_journal(client, make_user, auth_header):
    coach_a = make_user(role='coach', username='coach_ja@test.local', subscription_tier=3)
    coach_b = make_user(role='coach', username='coach_jb@test.local', subscription_tier=3)
    athlete_b = make_user(role='athlete', username='ath_jb@test.local', coach_id=coach_b.id)

    from app import db
    from app.models import JournalEntry
    entry = JournalEntry(athlete_id=athlete_b.id, entry_date=date.today(), weight=80)
    db.session.add(entry)
    db.session.commit()
    entry_id = entry.id

    res = client.put(
        f'/api/journal/{entry_id}',
        headers=auth_header(coach_a),
        json={'weight': 99},
    )
    assert res.status_code == 403


def test_coach_can_manage_own_athlete_program(client, make_user, auth_header):
    coach = make_user(role='coach', username='coach_own@test.local', subscription_tier=3)
    athlete = make_user(role='athlete', username='ath_own@test.local', coach_id=coach.id)

    from app import db
    from app.models import Program
    prog = Program(name='Prog A', athlete_id=athlete.id, coach_id=coach.id)
    db.session.add(prog)
    db.session.commit()

    res = client.get(f'/api/programs/{prog.id}', headers=auth_header(coach))
    assert res.status_code == 200
    assert res.get_json()['name'] == 'Prog A'


def test_admin_can_access_any_program(client, make_user, auth_header):
    admin = make_user(role='admin', username='admin@test.local')
    coach = make_user(role='coach', username='coach_adm@test.local', subscription_tier=3)
    athlete = make_user(role='athlete', username='ath_adm@test.local', coach_id=coach.id)

    from app import db
    from app.models import Program
    prog = Program(name='Prog Admin', athlete_id=athlete.id, coach_id=coach.id)
    db.session.add(prog)
    db.session.commit()

    res = client.get(f'/api/programs/{prog.id}', headers=auth_header(admin))
    assert res.status_code == 200


def test_mark_bilan_requires_ownership(client, make_user, auth_header):
    coach_a = make_user(role='coach', username='coach_ba@test.local', subscription_tier=3)
    coach_b = make_user(role='coach', username='coach_bb@test.local', subscription_tier=3)
    athlete_b = make_user(role='athlete', username='ath_bb@test.local', coach_id=coach_b.id)

    res = client.post(
        '/api/coach/bilan-hebdo/mark',
        headers=auth_header(coach_a),
        json={'athlete_id': athlete_b.id},
    )
    assert res.status_code == 403


def test_mark_bilan_own_athlete_ok(client, make_user, auth_header):
    coach = make_user(role='coach', username='coach_bm@test.local', subscription_tier=3)
    athlete = make_user(role='athlete', username='ath_bm@test.local', coach_id=coach.id)

    res = client.post(
        '/api/coach/bilan-hebdo/mark',
        headers=auth_header(coach),
        json={'athlete_id': athlete.id},
    )
    assert res.status_code == 200
    assert res.get_json()['done'] is True


def test_stripe_webhook_fail_closed_outside_dev(app, client):
    app.config['IS_DEVELOPMENT'] = False
    app.config['STRIPE_WEBHOOK_SECRET'] = ''
    app.config['STRIPE_SECRET_KEY'] = 'sk_test_dummy'
    res = client.post('/api/billing/webhook', data=b'{}', content_type='application/json')
    assert res.status_code == 503
    body = res.get_json()
    assert body.get('code') == 'WEBHOOK_SECRET_REQUIRED'


def test_stripe_webhook_dev_without_secret_parses(app, client):
    app.config['IS_DEVELOPMENT'] = True
    app.config['STRIPE_WEBHOOK_SECRET'] = ''
    app.config['STRIPE_SECRET_KEY'] = 'sk_test_dummy'
    res = client.post(
        '/api/billing/webhook',
        json={'type': 'ping', 'data': {'object': {}}},
    )
    assert res.status_code == 200


def test_demo_athlete_excluded_from_quota(make_user):
    coach = make_user(role='coach', username='coach_q@test.local', subscription_tier=1)  # limit 3
    make_user(role='athlete', username='real1@test.local', coach_id=coach.id)
    make_user(role='athlete', username='demo@test.local', coach_id=coach.id, is_demo=True)

    from app.api import _coach_quota_count
    assert _coach_quota_count(coach.id) == 1


def test_search_athletes_masks_email(client, make_user, auth_header):
    coach = make_user(role='coach', username='coach_s@test.local', subscription_tier=3)
    make_user(role='athlete', username='orphan@example.com', email='orphan@example.com')

    # Exact email match
    res = client.get(
        '/api/coach/athletes/search',
        headers=auth_header(coach),
        query_string={'q': 'orphan@example.com'},
    )
    assert res.status_code == 200
    rows = res.get_json()
    assert len(rows) == 1
    assert rows[0]['email'] != 'orphan@example.com'
    assert '***' in rows[0]['email']

    # Partial email must not enumerate
    res2 = client.get(
        '/api/coach/athletes/search',
        headers=auth_header(coach),
        query_string={'q': 'orphan@'},
    )
    assert res2.status_code == 200
    assert res2.get_json() == []
