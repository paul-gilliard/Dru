#!/usr/bin/env python3
"""
Script to insert exercise bank into the database
Run from project root: python insert_exercises.py
"""

from app import create_app, db
from app.models import Exercise

# Exercise data: (name, muscle_group)
EXERCISES = [
    ("belt squat", "LEGS"),
    ("crunch machine", "ABDOS"),
    ("curl haltères alternés (coude sur banc)", "BICEPS"),
    ("curl haltères alternés debout", "BICEPS"),
    ("curl poulie", "BICEPS"),
    ("curl pupitre (technogym)", "BICEPS"),
    ("Dévelope militaire (techno)", "EPAULES"),
    ("développé couché (hammer)", "PEC"),
    ("développé couché haltères", "PEC"),
    ("développé couché incliné haltères", "PEC"),
    ("développé couché incliné machine guidée", "PEC"),
    ("développé incliné (hammer)", "PEC"),
    ("dips", "PEC"),
    ("développé militaire barre debout", "EPAULES"),
    ("développé militaire haltères", "EPAULES"),
    ("développé militaire (hammer)", "EPAULES"),
    ("développé militaire (technogym)", "EPAULES"),
    ("dips machine (pure strength)", "TRICEPS"),
    ("dips triceps (technogym)", "TRICEPS"),
    ("extension triceps poulie haute", "TRICEPS"),
    ("écarté pecs technogym", "PEC"),
    ("élévation frontale poulie", "EPAULES"),
    ("élévation latérale (hammer)", "EPAULES"),
    ("élévation latérale poulie complète (hammer)", "EPAULES"),
    ("élévation latérale poulies", "EPAULES"),
    ("glutes harm raise", "ISCHIO"),
    ("hack squat", "LEGS"),
    ("leg curl", "ISCHIO"),
    ("leg extension", "QUAD"),
    ("magyc triceps", "TRICEPS"),
    ("mollets assis", "MOLLET"),
    ("mollets debout", "MOLLET"),
    ("mollets jambes tendus", "MOLLET"),
    ("relevé de genoux", "ABDOS"),
    ("extension dos poulie", "DOS"),
    ("rowing", "DOS"),
    ("tirage horizontal", "DOS"),
    ("tirage vertical hammer (trapèze)", "DOS"),
    ("Tirage vertical hammer unilatéral", "DOS"),
    ("tirage vertical poulie", "DOS"),
    ("traction", "DOS"),
    ("vis a vis haut de pecs", "PEC"),
    ("fentes smith's machine", "LEGS"),
    ("presse a cuisse", "LEGS"),
    ("iso latéral leg press (hammer)", "LEGS"),
    ("développé décliné haltères", "LEGS"),
    ("rowing bucheron", "DOS"),
    ("tirage horizontal unilatral (technogym)", "DOS"),
    ("hip trust (hammer)", "LEGS"),
    ("développé couché prise sérrée", "TRICEPS"),
    ("adducteurs (machine)", "LEGS"),
    ("abducteurs (machine)", "LEGS"),
    ("fentes bulgare", "LEGS"),
    ("extension hanche", "LEGS"),
    ("soulevé de terre jambes tendus", "LEGS"),
    ("tirage horizontal pure strengh", "DOS"),
    ("élévation latérale panatta", "EPAULES"),
    ("extension triceps poulie basse", "TRICEPS"),
    ("crunch poulie", "ABDOS"),
    ("pendulum squat", "LEGS"),
]

def insert_exercises():
    """Insert all exercises into the database"""
    app = create_app()
    with app.app_context():
        # Check existing exercises
        existing_count = Exercise.query.count()
        print(f"Exercices existants: {existing_count}")
        
        # Try to insert each exercise
        inserted = 0
        skipped = 0
        
        for name, muscle_group in EXERCISES:
            # Check if exercise already exists
            existing = Exercise.query.filter_by(name=name).first()
            if existing:
                print(f"⊘ Existe déjà: {name}")
                skipped += 1
            else:
                try:
                    exercise = Exercise(name=name, muscle_group=muscle_group)
                    db.session.add(exercise)
                    print(f"✓ Ajouté: {name} ({muscle_group})")
                    inserted += 1
                except Exception as e:
                    print(f"✗ Erreur pour {name}: {e}")
        
        # Commit all at once
        try:
            db.session.commit()
            print(f"\n✓ Succès! {inserted} exercices insérés, {skipped} existants")
        except Exception as e:
            db.session.rollback()
            print(f"\n✗ Erreur lors de la sauvegarde: {e}")

if __name__ == '__main__':
    insert_exercises()
