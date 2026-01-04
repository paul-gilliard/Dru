#!/usr/bin/env python3
"""
Force recreate Food table with proper schema
Run this once to fix the nullable columns issue
"""
from app import create_app, db
from app.models import Food

app = create_app()

with app.app_context():
    print("🔧 Fixing Food table schema...")
    
    try:
        # Drop the food table
        print("  - Dropping old food table...")
        db.session.execute(db.text("DROP TABLE IF EXISTS food"))
        db.session.commit()
        print("  ✓ Old table dropped")
        
        # Recreate with correct schema
        print("  - Creating new food table...")
        Food.__table__.create(db.engine, checkfirst=True)
        db.session.commit()
        print("  ✓ New table created with correct schema")
        
        print("\n✅ Food table schema fixed!")
        print("   proteins and lipids are now nullable")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        db.session.rollback()
