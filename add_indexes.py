"""Apply composite indexes idempotently on the live MySQL DB."""
import os
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import text
from app import create_app
from app.models import db

INDEXES = [
    ('journal_entry',     'idx_journal_athlete_date',          ['athlete_id', 'entry_date']),
    ('performance_entry', 'idx_perf_athlete_date',             ['athlete_id', 'entry_date']),
    ('performance_entry', 'idx_perf_athlete_exercise_date',    ['athlete_id', 'exercise', 'entry_date']),
]

app = create_app()
with app.app_context():
    with db.engine.connect() as conn:
        for table, name, cols in INDEXES:
            exists = conn.execute(text(
                "SELECT COUNT(*) FROM information_schema.statistics "
                "WHERE table_schema=DATABASE() AND table_name=:t AND index_name=:n"
            ), {'t': table, 'n': name}).scalar()
            if exists:
                print(f"  = {name} already exists on {table}")
                continue
            cols_sql = ', '.join(cols)
            print(f"  + creating {name} on {table}({cols_sql}) ...")
            conn.execute(text(f"CREATE INDEX {name} ON {table} ({cols_sql})"))
            try:
                conn.commit()
            except Exception:
                pass
    print("Done.")
