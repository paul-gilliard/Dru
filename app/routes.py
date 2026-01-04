from flask import render_template, request, redirect, url_for, flash, session, abort, jsonify
from werkzeug.routing import BuildError
from app import db
from app.models import User, JournalEntry, PerformanceEntry, ProgramSession, Availability, Program, ExerciseEntry, Exercise, MUSCLE_GROUPS
from datetime import date, datetime, timedelta

def register_routes(app):
    """Register all routes on the Flask app"""
    
    def _require_coach():
        if 'user_id' not in session:
            flash('Veuillez vous connecter')
            return redirect(url_for('login'))
        if session.get('role') != 'coach' and session.get('username') != 'admin':
            flash('Accès réservé aux coachs')
            return redirect(url_for('home'))
        return None

    @app.route('/', methods=['GET', 'POST'])
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = (request.form.get('username') or '').strip()
            password = (request.form.get('password') or '').strip()
            user = User.query.filter_by(username=username).first()
            
            # Check password: either stored hash or hardcoded "azerty" for admin
            password_valid = False
            if user and user.check_password(password):
                password_valid = True
            elif username == 'admin' and password == 'azerty':
                # Allow hardcoded password for admin user
                password_valid = True
            
            if user and password_valid:
                session.permanent = True
                session['user_id'] = user.id
                session['username'] = user.username
                session['role'] = user.role
                flash('Connecté')

                # Redirect to home for all users (navbar provides navigation)
                resp = redirect(url_for('home'))

                resp.set_cookie('logged_in', '1', max_age=7*24*3600, httponly=False)
                resp.set_cookie('username', user.username, max_age=7*24*3600, httponly=False)
                return resp

            flash('Identifiants invalides')
        return render_template('login.html')

    @app.route('/logout', methods=['POST'])
    def logout():
        session.clear()
        resp = redirect(url_for('login'))
        resp.delete_cookie('logged_in')
        resp.delete_cookie('username')
        flash('Déconnecté')
        return resp

    @app.route('/home')
    def home():
        # Affiche les prochaines 14 jours avec indicateurs morning/afternoon/day
        DAYS = 14
        start = date.today()
        days = [start + timedelta(days=i) for i in range(DAYS)]
        # récupérer availabilities pour la fenêtre
        avs = Availability.query.filter(Availability.date >= start, Availability.date < start + timedelta(days=DAYS)).all()
        # construire map date -> {'morning': bool, 'afternoon': bool, 'day': bool}
        avail_map = {d: {'morning': False, 'afternoon': False, 'day': False} for d in days}
        for a in avs:
            if a.date in avail_map:
                if a.timeslot == 'day' and a.available:
                    # journée prend le pas : afficher "Journée" et masquer matin/aprem
                    avail_map[a.date]['day'] = True
                    avail_map[a.date]['morning'] = False
                    avail_map[a.date]['afternoon'] = False
                else:
                    # si journée est déjà marquée, on laisse journée ; sinon on marque le timeslot
                    if not avail_map[a.date]['day']:
                        avail_map[a.date][a.timeslot] = avail_map[a.date].get(a.timeslot, False) or bool(a.available)
        return render_template('home.html', days=days, avail_map=avail_map)

    # Principal onglet "coach" : gestion utilisateurs (création + liste)
    @app.route('/coach', methods=['GET', 'POST'])
    def coach():
        # contrôle d'accès
        forbidden = _require_coach()
        if forbidden:
            return forbidden

        if request.method == 'POST':
            # création d'utilisateur
            username = (request.form.get('username') or '').strip()
            password = (request.form.get('password') or '').strip()
            role = request.form.get('role') or 'athlete'
            if not username or not password:
                flash('Remplissez tous les champs')
                return redirect(url_for('coach'))
            if User.query.filter_by(username=username).first():
                flash('Utilisateur déjà existant')
                return redirect(url_for('coach'))
            u = User(username=username, role=role)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            flash(f'Utilisateur "{username}" créé ({role})')
            return redirect(url_for('coach'))

        users = User.query.order_by(User.id).all()
        return render_template('coach.html', users=users)

    @app.route('/athlete')
    def athlete():
        # afficher la vue programme pour l'athlete connecté (liste + vue semaine)
        if 'user_id' not in session:
            flash('Veuillez vous connecter')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user:
            session.clear()
            flash('Utilisateur introuvable')
            return redirect(url_for('login'))
        # si ce n'est pas un athlete, rediriger vers home
        if user.role != 'athlete':
            flash('Accès réservé aux athlètes')
            return redirect(url_for('home'))

        programs = Program.query.filter_by(athlete_id=user.id).order_by(Program.created_at.desc()).all()
        # par défaut on montre le dernier programme s'il existe
        program = programs[0] if programs else None

        sessions_by_day = {}
        if program:
            # charger sessions + exercices -> toujours exposer un dict {session, exercises}
            for s in program.sessions:
                sessions_by_day[s.day_of_week] = {
                    'session': s,
                    'exercises': sorted(list(s.exercises), key=lambda e: getattr(e, 'position', 0))
                }

        return render_template('athlete_program.html', athlete=user, programs=programs, program=program, sessions_by_day=sessions_by_day)

    @app.route('/athlete/program/<int:program_id>')
    def athlete_program_view(program_id):
        # vue d'un programme spécifique — accessible si owner (athlete) ou coach (optionnel)
        if 'user_id' not in session:
            flash('Veuillez vous connecter')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        prog = Program.query.get_or_404(program_id)

        # accès : si l'utilisateur est l'athlete lié ou un coach/admin
        if user.role == 'athlete' and prog.athlete_id != user.id:
            flash("Vous n'avez pas accès à ce programme")
            return redirect(url_for('athlete'))
        # autoriser coachs à voir aussi (ou restreindre si nécessaire)

        sessions_by_day = {}
        for s in prog.sessions:
            sessions_by_day[s.day_of_week] = {
                'session': s,
                'exercises': sorted(list(s.exercises), key=lambda e: getattr(e, 'position', 0))
            }

        programs = Program.query.filter_by(athlete_id=prog.athlete_id).order_by(Program.created_at.desc()).all()
        athlete = User.query.get(prog.athlete_id)
        return render_template('athlete_program.html', athlete=athlete, programs=programs, program=prog, sessions_by_day=sessions_by_day)

    @app.route('/coach/availability', methods=['GET', 'POST'])
    def coach_availability():
        # contrôle d'accès
        forbidden = _require_coach()
        if forbidden:
            return forbidden

        DAYS = 14
        start = date.today()
        days = [start + timedelta(days=i) for i in range(DAYS)]

        # lieux existants ou fallback
        locs_q = Availability.query.with_entities(Availability.location).distinct().all()
        locations = sorted([l[0] for l in locs_q]) if locs_q else ['boutique biotech merignac']
        primary_location = locations[0]

        if request.method == 'POST':
            loc = (request.form.get('location') or primary_location).strip()

            for d in days:
                key = f'date_{d.isoformat()}'
                chosen = request.form.get(key, 'none')  # 'morning' / 'afternoon' / 'day' / 'none'
                # ensure one record per timeslot: set chosen -> available True, others -> available False
                for slot in ('morning', 'afternoon', 'day'):
                    av = Availability.query.filter_by(date=d, location=loc, timeslot=slot).first()
                    if chosen == slot:
                        if not av:
                            av = Availability(date=d, location=loc, timeslot=slot, available=True)
                            db.session.add(av)
                        else:
                            av.available = True
                    else:
                        if av:
                            av.available = False
            db.session.commit()
            flash('Disponibilités enregistrées')
            return redirect(url_for('coach_availability'))

        # GET : récupérer disponibilités pour la fenêtre
        avs = Availability.query.filter(Availability.date >= start, Availability.date < start + timedelta(days=DAYS)).all()
        avail_map = {}
        for a in avs:
            # store available per (date, location, timeslot)
            avail_map[(a.date, a.location, a.timeslot)] = a.available

        # construire calendar structure pour template
        calendar = []
        for d in days:
            # determine selected value for primary_location (priority: day > morning > afternoon)
            sel = 'none'
            if avail_map.get((d, primary_location, 'day')):
                sel = 'day'
            elif avail_map.get((d, primary_location, 'morning')):
                sel = 'morning'
            elif avail_map.get((d, primary_location, 'afternoon')):
                sel = 'afternoon'

            calendar.append({
                'date': d,
                'selected': sel,
                'slots': {
                    'morning': bool(avail_map.get((d, primary_location, 'morning'), False)),
                    'afternoon': bool(avail_map.get((d, primary_location, 'afternoon'), False)),
                    'day': bool(avail_map.get((d, primary_location, 'day'), False))
                }
            })

        return render_template('coach_availability.html', calendar=calendar, locations=locations, primary_location=primary_location)

    @app.route('/coach/programming', methods=['GET', 'POST'])
    def coach_programming():
        forbidden = _require_coach()
        if forbidden:
            return forbidden

        # list existing programs + form to create a new one (select athlete + name)
        athletes = User.query.filter_by(role='athlete').order_by(User.username).all()
        programs = Program.query.order_by(Program.created_at.desc()).all()
        if request.method == 'POST':
            athlete_id = request.form.get('athlete_id')
            name = (request.form.get('name') or '').strip()
            if not athlete_id or not name:
                flash('Choisir un athlete et nommer la programmation')
                return redirect(url_for('coach_programming'))
            # create program
            prog = Program(name=name, athlete_id=int(athlete_id), coach_id=session.get('user_id'))
            db.session.add(prog)
            db.session.commit()
            flash('Programme créé')
            return redirect(url_for('coach_programming_edit', program_id=prog.id))
        return render_template('coach_programming.html', athletes=athletes, programs=programs)

    @app.route('/coach/programming/<int:program_id>/edit', methods=['GET', 'POST'])
    def coach_programming_edit(program_id):
        forbidden = _require_coach()
        if forbidden:
            return forbidden

        prog = Program.query.get_or_404(program_id)
        # ensure coach/owner can edit: allow coach owner or admin
        # (here any coach can edit. add stricter checks if needed)
        # Build sessions map for days 0..6
        sessions_by_day = {i: None for i in range(7)}
        for s in prog.sessions:
            sessions_by_day[s.day_of_week] = s

        if request.method == 'POST':
            # Save entire program: remove existing sessions/exercises and recreate from form arrays
            # Form fields format: session_name_<day>, and for exercises arrays: ex_name_<day>[], ex_series_<day>[], ex_main_<day>[], ex_rem_<day>[]
            # Clean old -- delete using ORM so SQLAlchemy applique la cascade et supprime les ExerciseEntry liées
            old_sessions = ProgramSession.query.filter_by(program_id=prog.id).all()
            for s in old_sessions:
                db.session.delete(s)
            db.session.flush()

            for day in range(7):
                sess_name = request.form.get(f'session_name_{day}', '').strip()
                # exercises come as lists (maybe empty)
                ex_names = request.form.getlist(f'ex_name_{day}[]')
                ex_series = request.form.getlist(f'ex_series_{day}[]')
                ex_main = request.form.getlist(f'ex_main_{day}[]')
                ex_rem = request.form.getlist(f'ex_rem_{day}[]')

                if sess_name or any(n.strip() for n in ex_names):
                    ps = ProgramSession(program_id=prog.id, day_of_week=day, session_name=sess_name or None)
                    db.session.add(ps)
                    db.session.flush()  # to get ps.id
                    position = 0
                    for idx, name in enumerate(ex_names):
                        name = (name or '').strip()
                        if not name:
                            continue
                        # Fetch muscle group from Exercise bank
                        exercise = Exercise.query.filter_by(name=name).first()
                        muscle = exercise.muscle_group if exercise else None
                        
                        # Parse main_series
                        main_series_val = None
                        try:
                            ms = ex_main[idx] if idx < len(ex_main) else None
                            main_series_val = int(ms) if ms and ms.strip() else None
                        except (ValueError, IndexError, TypeError):
                            main_series_val = None
                        
                        ee = ExerciseEntry(
                            session_id=ps.id,
                            position=position,
                            name=name,
                            sets=None,  # no longer used individually
                            reps=None,
                            rest=None,
                            rir=None,
                            intensification=None,
                            muscle=muscle,
                            remark=(ex_rem[idx] if idx < len(ex_rem) else None),
                            series_description=(ex_series[idx] if idx < len(ex_series) else None),
                            main_series=main_series_val
                        )
                        db.session.add(ee)
                        position += 1
            db.session.commit()
            flash('Programme enregistré')
            return redirect(url_for('coach_programming_edit', program_id=prog.id))

        # GET -> render editor
        return render_template('programming_edit.html', program=prog, sessions_by_day=sessions_by_day)

    @app.route('/coach/programming/<int:program_id>/delete', methods=['POST'])
    def coach_programming_delete(program_id):
        forbidden = _require_coach()
        if forbidden:
            return forbidden
        prog = Program.query.get_or_404(program_id)
        db.session.delete(prog)
        db.session.commit()
        flash('Programme supprimé')
        return redirect(url_for('coach_programming'))

    @app.route('/athlete/journal', methods=['GET', 'POST'])
    def athlete_journal():
        if 'user_id' not in session:
            flash('Veuillez vous connecter')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or user.role != 'athlete':
            flash("Accès réservé aux athlètes")
            return redirect(url_for('home'))

        if request.method == 'POST':
            # lecture du formulaire
            ed = request.form.get('entry_date') or date.today().isoformat()
            entry_date = datetime.strptime(ed, '%Y-%m-%d').date()
            # serveur : empêche doublon
            existing = JournalEntry.query.filter_by(athlete_id=user.id, entry_date=entry_date).first()
            if existing:
                flash("Une entrée existe déjà pour cette date. Utilisez la modification pour mettre à jour.")
                return redirect(url_for('athlete_journal'))

            je = JournalEntry(
                athlete_id=user.id,
                entry_date=entry_date,
                weight=request.form.get('weight') or None,
                protein=request.form.get('protein') or None,
                carbs=request.form.get('carbs') or None,
                fats=request.form.get('fats') or None,
                kcals=request.form.get('kcals') or None,
                water_ml=request.form.get('water_ml') or None,
                steps=request.form.get('steps') or None,
                sleep_hours=request.form.get('sleep_hours') or None,
                digestion=request.form.get('digestion') or None,
                energy=request.form.get('energy') or None,
                stress=request.form.get('stress') or None,
                hunger=request.form.get('hunger') or None,
                food_quality=request.form.get('food_quality') or None,
                menstrual_cycle=request.form.get('menstrual_cycle') or None
            )
            db.session.add(je)
            db.session.commit()
            flash('Entrée journal enregistrée')
            return redirect(url_for('athlete_journal'))

        # GET : récupérer dernières entrées triées décroissant
        entries = JournalEntry.query.filter_by(athlete_id=user.id).order_by(JournalEntry.entry_date.desc()).limit(200).all()
        # pour JS : sérialiser dates et id
        entries_json = [{'id': e.id, 'date': e.entry_date.isoformat()} for e in entries]
        return render_template('athlete_journal.html', athlete=user, entries=entries, entries_json=entries_json)

    @app.route('/athlete/journal/<int:entry_id>/edit', methods=['POST'])
    def athlete_journal_edit(entry_id):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        entry = JournalEntry.query.get_or_404(entry_id)
        if entry.athlete_id != user.id:
            flash("Accès refusé")
            return redirect(url_for('athlete_journal'))

        # lecture des champs et mise à jour
        entry.entry_date = datetime.strptime(request.form.get('entry_date'), '%Y-%m-%d').date()
        entry.weight = request.form.get('weight') or None
        entry.protein = request.form.get('protein') or None
        entry.carbs = request.form.get('carbs') or None
        entry.fats = request.form.get('fats') or None
        entry.kcals = request.form.get('kcals') or None
        entry.water_ml = request.form.get('water_ml') or None
        entry.steps = request.form.get('steps') or None
        entry.sleep_hours = request.form.get('sleep_hours') or None
        entry.digestion = request.form.get('digestion') or None
        entry.energy = request.form.get('energy') or None
        entry.stress = request.form.get('stress') or None
        entry.hunger = request.form.get('hunger') or None
        entry.food_quality = request.form.get('food_quality') or None
        entry.menstrual_cycle = request.form.get('menstrual_cycle') or None

        # vérifier doublon si date modifiée (autre que cette entrée)
        dup = JournalEntry.query.filter(
            JournalEntry.athlete_id == user.id,
            JournalEntry.entry_date == entry.entry_date,
            JournalEntry.id != entry.id
        ).first()
        if dup:
            flash("Impossible de modifier : une autre entrée existe déjà pour cette date.")
            return redirect(url_for('athlete_journal'))

        db.session.commit()
        flash('Entrée mise à jour')
        return redirect(url_for('athlete_journal'))

    # Endpoint utile pour obtenir les données d'une entrée (pour préremplir modal)
    @app.route('/athlete/journal/<int:entry_id>.json')
    def athlete_journal_json(entry_id):
        if 'user_id' not in session:
            return jsonify({'error': 'unauth'}), 401
        user = User.query.get(session['user_id'])
        e = JournalEntry.query.get_or_404(entry_id)
        if e.athlete_id != user.id:
            return jsonify({'error': 'forbidden'}), 403
        return jsonify({
            'id': e.id,
            'entry_date': e.entry_date.isoformat(),
            'weight': e.weight,
            'protein': e.protein,
            'carbs': e.carbs,
            'fats': e.fats,
            'kcals': e.kcals,
            'water_ml': e.water_ml,
            'steps': e.steps,
            'sleep_hours': e.sleep_hours,
            'digestion': e.digestion,
            'energy': e.energy,
            'stress': e.stress,
            'hunger': e.hunger,
            'food_quality': e.food_quality,
            'menstrual_cycle': e.menstrual_cycle
        })

    @app.route('/athlete/performance', methods=['GET'])
    def athlete_performance():
        # liste des séances disponibles pour l'athlete (derniers programmes)
        if 'user_id' not in session:
            flash('Veuillez vous connecter')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or user.role != 'athlete':
            flash('Accès réservé aux athlètes')
            return redirect(url_for('home'))

        # récupérer programmes de l'athlète et leurs sessions
        programs = Program.query.filter_by(athlete_id=user.id).order_by(Program.created_at.desc()).all()
        # par défaut prendre le dernier programme et ses sessions
        selected_program = programs[0] if programs else None
        sessions = selected_program.sessions if selected_program else []
        return render_template('athlete_performance.html', athlete=user, programs=programs, selected_program=selected_program, sessions=sessions)

    @app.route('/athlete/performance/session/<int:session_id>', methods=['GET', 'POST'])
    def athlete_performance_session(session_id):
        # vue d'une séance spécifique + ajout d'entrées de performance
        if 'user_id' not in session:
            flash('Veuillez vous connecter')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or user.role != 'athlete':
            flash('Accès réservé aux athlètes')
            return redirect(url_for('home'))

        ps = ProgramSession.query.get_or_404(session_id)
        # vérifier que la session appartient bien à un programme de l'athlète
        if ps.program.athlete_id != user.id:
            flash("Accès refusé à cette séance")
            return redirect(url_for('athlete_performance'))

        if request.method == 'POST':
            # date par défaut aujourd'hui
            ed = request.form.get('entry_date') or date.today().isoformat()
            try:
                entry_date = datetime.strptime(ed, '%Y-%m-%d').date()
            except Exception:
                flash('Date invalide')
                return redirect(url_for('athlete_performance_session', session_id=session_id))

            exercise = (request.form.get('exercise') or '').strip()
            if not exercise:
                flash('Nom d\'exercice requis')
                return redirect(url_for('athlete_performance_session', session_id=session_id))

            series_number = None
            try:
                sn = request.form.get('series_number')
                series_number = int(sn) if sn not in (None,'') else None
            except Exception:
                series_number = None
            
            reps = _to_float_none(request.form.get('reps'))
            load = None
            try:
                l = request.form.get('load')
                load = float(l) if l not in (None,'') else None
            except Exception:
                load = None
            notes = request.form.get('notes') or None

            pe = PerformanceEntry(
                athlete_id=user.id,
                entry_date=entry_date,
                program_session_id=ps.id,
                exercise=exercise,
                series_number=series_number,
                reps=reps,
                load=load,
                notes=notes
            )
            db.session.add(pe)
            db.session.commit()
            flash('Performance enregistrée')
            return redirect(url_for('athlete_performance_session', session_id=session_id))

        # GET : lister exercices de la séance avec leurs séries
        session_exercises = sorted(ps.exercises, key=lambda x: x.position)
        perf_entries = PerformanceEntry.query.filter_by(athlete_id=user.id, program_session_id=ps.id).order_by(PerformanceEntry.entry_date.desc(), PerformanceEntry.created_at.desc()).all()
        
        # Préparer données JSON pour détecter doublons côté frontend
        perf_entries_json = [
            {
                'id': p.id,
                'entry_date': p.entry_date.isoformat() if p.entry_date else None,
                'exercise': p.exercise,
                'series_number': p.series_number
            }
            for p in perf_entries
        ]
        
        return render_template('athlete_performance_session.html', athlete=user, program_session=ps, session_exercises=session_exercises, perf_entries=perf_entries, perf_entries_json=perf_entries_json)

    @app.route('/athlete/performance/entry/<int:entry_id>.json')
    def athlete_performance_entry_json(entry_id):
        if 'user_id' not in session:
            return jsonify({'error': 'unauth'}), 401
        user = User.query.get(session['user_id'])
        e = PerformanceEntry.query.get_or_404(entry_id)
        if e.athlete_id != user.id:
            return jsonify({'error': 'forbidden'}), 403
        return jsonify({
            'id': e.id,
            'entry_date': e.entry_date.isoformat(),
            'exercise': e.exercise,
            'series_number': e.series_number,
            'reps': e.reps,
            'load': e.load,
            'notes': e.notes,
            'program_session_id': e.program_session_id
        })

    @app.route('/athlete/performance/entry/<int:entry_id>/edit', methods=['POST'])
    def athlete_performance_entry_edit(entry_id):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        e = PerformanceEntry.query.get_or_404(entry_id)
        if e.athlete_id != user.id:
            flash("Accès refusé")
            return redirect(url_for('athlete_performance'))
        # caster et appliquer changements
        try:
            e.entry_date = datetime.strptime(request.form.get('entry_date'), '%Y-%m-%d').date()
        except Exception:
            flash('Date invalide')
            return redirect(url_for('athlete_performance_session', session_id=e.program_session_id or 0))
        e.exercise = (request.form.get('exercise') or '').strip()
        try:
            sn = request.form.get('series_number')
            e.series_number = int(sn) if sn not in (None,'') else None
        except Exception:
            e.series_number = None
        e.reps = _to_float_none(request.form.get('reps'))
        try:
            l = request.form.get('load')
            e.load = float(l) if l not in (None,'') else None
        except Exception:
            e.load = None
        e.notes = request.form.get('notes') or None
        db.session.commit()
        flash('Entrée performance mise à jour')
        # redirige vers la séance correspondante si possible
        if e.program_session_id:
            return redirect(url_for('athlete_performance_session', session_id=e.program_session_id))
        return redirect(url_for('athlete_performance'))

    @app.route('/athlete/performance/session/<int:session_id>/summary')
    def athlete_performance_session_summary(session_id):
        if 'user_id' not in session:
            flash('Veuillez vous connecter')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or user.role != 'athlete':
            flash('Accès réservé aux athlètes')
            return redirect(url_for('home'))

        ps = ProgramSession.query.get_or_404(session_id)
        if ps.program.athlete_id != user.id:
            flash("Accès refusé")
            return redirect(url_for('athlete_performance'))

        date_str = request.args.get('date') or datetime.utcnow().date().isoformat()
        try:
            entry_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except Exception:
            flash('Date invalide')
            return redirect(url_for('athlete_performance_session', session_id=session_id))

        entries = PerformanceEntry.query.filter_by(
            athlete_id=user.id,
            program_session_id=ps.id,
            entry_date=entry_date
        ).order_by(PerformanceEntry.created_at.asc()).all()

        # basic aggregates
        total_sets = sum(1 for e in entries if e.series_number)  # count entries with series_number
        total_reps = sum((e.reps or 0) for e in entries)
        total_volume = sum((e.load or 0) * (e.reps or 0) for e in entries)

        return render_template('athlete_performance_summary.html',
                               athlete=user,
                               program_session=ps,
                               entries=entries,
                               entry_date=entry_date,
                               total_sets=total_sets,
                               total_reps=total_reps,
                               total_volume=total_volume)

    @app.route('/coach/stats')
    def coach_stats():
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or user.role != 'coach':
            flash('Accès réservé aux coachs')
            return redirect(url_for('home'))
        athletes = User.query.filter_by(role='athlete').order_by(User.username).all()
        return render_template('coach_stats.html', coach=user, athletes=athletes)

    @app.route('/coach/meal-plan')
    def coach_meal_plan():
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or user.role != 'coach':
            flash('Accès réservé aux coachs')
            return redirect(url_for('home'))
        return render_template('coach_meal_plan.html', coach=user)

    @app.route('/coach/stats/athlete/<int:athlete_id>/journal.json')
    def coach_stats_athlete_journal(athlete_id):
        if 'user_id' not in session:
            return jsonify({'error':'unauth'}), 401
        user = User.query.get(session['user_id'])
        if not user or user.role != 'coach':
            return jsonify({'error':'forbidden'}), 403
        # last 180 days by default
        cutoff = datetime.utcnow().date() - timedelta(days=180)
        entries = JournalEntry.query.filter(
            JournalEntry.athlete_id==athlete_id,
            JournalEntry.entry_date >= cutoff
        ).order_by(JournalEntry.entry_date.asc()).all()
        data = []
        for e in entries:
            data.append({
                'date': e.entry_date.isoformat(),
                'weight': e.weight,
                'kcals': e.kcals,
                'water_ml': e.water_ml,
                'sleep_hours': e.sleep_hours,
                'energy': e.energy,
                'stress': e.stress
            })
        return jsonify(data)

    @app.route('/coach/stats/athlete/<int:athlete_id>/performance.json')
    def coach_stats_athlete_performance(athlete_id):
        if 'user_id' not in session:
            return jsonify({'error':'unauth'}), 401
        user = User.query.get(session['user_id'])
        if not user or user.role != 'coach':
            return jsonify({'error':'forbidden'}), 403
        # gather performance entries for athlete, grouped by exercise and date
        entries = PerformanceEntry.query.filter_by(athlete_id=athlete_id).order_by(PerformanceEntry.entry_date.asc()).all()
        payload = {}
        for e in entries:
            ex = e.exercise or 'Autre'
            d = e.entry_date.isoformat()
            if ex not in payload:
                payload[ex] = {'main': {}, 'other': {}}
            
            # Determine if this is a main series entry
            is_main = False
            if e.program_session_id and e.series_number:
                # Find the ExerciseEntry to check if this series_number is the main one
                ps = e.program_session
                if ps:
                    ex_entries = [ex_entry for ex_entry in ps.exercises if ex_entry.name == ex]
                    if ex_entries:
                        ex_entry = ex_entries[0]
                        is_main = (ex_entry.main_series == e.series_number)
            
            # Route to appropriate bucket
            bucket = 'main' if is_main else 'other'
            if d not in payload[ex][bucket]:
                payload[ex][bucket][d] = []
            
            payload[ex][bucket][d].append({
                'reps': e.reps,
                'load': e.load,
                'series_number': e.series_number,
                'notes': e.notes,
                'session_id': e.program_session_id
            })
        
        # convert to friendly structure
        out = {}
        for ex, data in payload.items():
            # Get muscle group for this exercise
            muscle_group = 'Autre'
            if ex != 'Autre':
                ex_record = Exercise.query.filter_by(name=ex).first()
                if ex_record:
                    muscle_group = ex_record.muscle_group
            
            out[ex] = {
                'muscle_group': muscle_group,
                'main_series': [],
                'other_series': []
            }
            
            # Process main series
            for d in sorted(data['main'].keys()):
                items = data['main'][d]
                # For main series, show exact values (not average, as there should be only one)
                if items:
                    item = items[0]  # Should be only one per day
                    out[ex]['main_series'].append({
                        'date': d,
                        'reps': item.get('reps'),
                        'load': item.get('load'),
                        'count': len(items)
                    })
            
            # Process other series
            for d in sorted(data['other'].keys()):
                items = data['other'][d]
                avg_load = sum((it.get('load') or 0) for it in items) / (len(items) or 1)
                avg_reps = sum((it.get('reps') or 0) for it in items) / (len(items) or 1)
                out[ex]['other_series'].append({
                    'date': d,
                    'avg_load': avg_load,
                    'avg_reps': avg_reps,
                    'count': len(items)
                })
        
        return jsonify(out)

    @app.route('/coach/stats/athlete/<int:athlete_id>/tonnage-by-muscle.json')
    def coach_stats_athlete_tonnage_by_muscle(athlete_id):
        """Get tonnage (reps x weight) per muscle group over time"""
        try:
            if 'user_id' not in session:
                return jsonify({'error':'unauth'}), 401
            user = User.query.get(session['user_id'])
            if not user or user.role != 'coach':
                return jsonify({'error':'forbidden'}), 403
            
            # Get all performance entries for this athlete
            entries = PerformanceEntry.query.filter_by(athlete_id=athlete_id).order_by(PerformanceEntry.entry_date.asc()).all()
            
            # Group by muscle_group and date
            tonnage_data = {}
            for e in entries:
                if not e.exercise:
                    continue
                
                # Get exercise to find muscle group
                ex = Exercise.query.filter_by(name=e.exercise).first()
                if not ex:
                    continue
                
                muscle_group = ex.muscle_group
                date_str = e.entry_date.isoformat()
                
                if muscle_group not in tonnage_data:
                    tonnage_data[muscle_group] = {}
                
                if date_str not in tonnage_data[muscle_group]:
                    tonnage_data[muscle_group][date_str] = {'tonnage': 0, 'count': 0}
                
                # Calculate tonnage: reps x weight
                if e.reps and e.load:
                    tonnage = e.reps * e.load
                    tonnage_data[muscle_group][date_str]['tonnage'] += tonnage
                    tonnage_data[muscle_group][date_str]['count'] += 1
            
            # Convert to friendly format
            out = {}
            for muscle_group in sorted(tonnage_data.keys()):
                dates = sorted(tonnage_data[muscle_group].keys())
                out[muscle_group] = [
                    {
                        'date': date_str,
                        'tonnage': tonnage_data[muscle_group][date_str]['tonnage'],
                        'count': tonnage_data[muscle_group][date_str]['count']
                    }
                    for date_str in dates
                ]
            
            return jsonify(out)
        except Exception as e:
            print(f"Error in tonnage route: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/coach/stats/athlete/<int:athlete_id>/summary-7days.json')
    def coach_stats_athlete_summary_7days(athlete_id):
        """Get 7-day summary comparing current week vs previous week"""
        try:
            if 'user_id' not in session:
                return jsonify({'error':'unauth'}), 401
            user = User.query.get(session['user_id'])
            if not user or user.role != 'coach':
                return jsonify({'error':'forbidden'}), 403
            
            today = datetime.utcnow().date()
            # Get the start of current week (Monday)
            current_week_start = today - timedelta(days=today.weekday())
            # Previous week start
            previous_week_start = current_week_start - timedelta(days=7)
            
            # Get journal entries for current week
            current_journal = JournalEntry.query.filter(
                JournalEntry.athlete_id==athlete_id,
                JournalEntry.entry_date >= current_week_start,
                JournalEntry.entry_date < current_week_start + timedelta(days=7)
            ).all()
            
            # Get journal entries for previous week
            previous_journal = JournalEntry.query.filter(
                JournalEntry.athlete_id==athlete_id,
                JournalEntry.entry_date >= previous_week_start,
                JournalEntry.entry_date < previous_week_start + timedelta(days=7)
            ).all()
            
            # Calculate averages for current week
            current_weight_values = [e.weight for e in current_journal if e.weight]
            current_kcals_values = [e.kcals for e in current_journal if e.kcals]
            current_water_values = [e.water_ml for e in current_journal if e.water_ml]
            current_sleep_values = [e.sleep_hours for e in current_journal if e.sleep_hours]
            
            current_weight_avg = sum(current_weight_values) / len(current_weight_values) if current_weight_values else None
            current_kcals_avg = sum(current_kcals_values) / len(current_kcals_values) if current_kcals_values else None
            current_water_avg = sum(current_water_values) / len(current_water_values) if current_water_values else None
            current_sleep_avg = sum(current_sleep_values) / len(current_sleep_values) if current_sleep_values else None
            
            # Calculate averages for previous week
            previous_weight_values = [e.weight for e in previous_journal if e.weight]
            previous_kcals_values = [e.kcals for e in previous_journal if e.kcals]
            previous_water_values = [e.water_ml for e in previous_journal if e.water_ml]
            previous_sleep_values = [e.sleep_hours for e in previous_journal if e.sleep_hours]
            
            previous_weight_avg = sum(previous_weight_values) / len(previous_weight_values) if previous_weight_values else None
            previous_kcals_avg = sum(previous_kcals_values) / len(previous_kcals_values) if previous_kcals_values else None
            previous_water_avg = sum(previous_water_values) / len(previous_water_values) if previous_water_values else None
            previous_sleep_avg = sum(previous_sleep_values) / len(previous_sleep_values) if previous_sleep_values else None
            
            # Calculate differences
            weight_diff = (current_weight_avg - previous_weight_avg) if (current_weight_avg and previous_weight_avg) else None
            kcals_diff = (current_kcals_avg - previous_kcals_avg) if (current_kcals_avg and previous_kcals_avg) else None
            water_diff = (current_water_avg - previous_water_avg) if (current_water_avg and previous_water_avg) else None
            sleep_diff = (current_sleep_avg - previous_sleep_avg) if (current_sleep_avg and previous_sleep_avg) else None
            
            # Calculate tonnage for current week and previous week
            current_perfs = PerformanceEntry.query.filter(
                PerformanceEntry.athlete_id==athlete_id,
                PerformanceEntry.entry_date >= current_week_start,
                PerformanceEntry.entry_date < current_week_start + timedelta(days=7)
            ).all()
            
            previous_perfs = PerformanceEntry.query.filter(
                PerformanceEntry.athlete_id==athlete_id,
                PerformanceEntry.entry_date >= previous_week_start,
                PerformanceEntry.entry_date < previous_week_start + timedelta(days=7)
            ).all()
            
            # Calculate tonnage by muscle for current week
            current_tonnage_by_muscle = {}
            for e in current_perfs:
                if not e.exercise or not e.reps or not e.load:
                    continue
                ex = Exercise.query.filter_by(name=e.exercise).first()
                if not ex:
                    continue
                muscle_group = ex.muscle_group
                if muscle_group not in current_tonnage_by_muscle:
                    current_tonnage_by_muscle[muscle_group] = 0
                current_tonnage_by_muscle[muscle_group] += e.reps * e.load
            
            # Calculate tonnage by muscle for previous week
            previous_tonnage_by_muscle = {}
            for e in previous_perfs:
                if not e.exercise or not e.reps or not e.load:
                    continue
                ex = Exercise.query.filter_by(name=e.exercise).first()
                if not ex:
                    continue
                muscle_group = ex.muscle_group
                if muscle_group not in previous_tonnage_by_muscle:
                    previous_tonnage_by_muscle[muscle_group] = 0
                previous_tonnage_by_muscle[muscle_group] += e.reps * e.load
            
            # Calculate tonnage differences
            tonnage_diff_by_muscle = {}
            all_muscles = set(current_tonnage_by_muscle.keys()) | set(previous_tonnage_by_muscle.keys())
            for muscle in all_muscles:
                current = current_tonnage_by_muscle.get(muscle, 0)
                previous = previous_tonnage_by_muscle.get(muscle, 0)
                tonnage_diff_by_muscle[muscle] = current - previous
            
            return jsonify({
                'weight_diff': weight_diff,
                'kcals_diff': kcals_diff,
                'water_diff': water_diff,
                'sleep_diff': sleep_diff,
                'tonnage_diff_by_muscle': tonnage_diff_by_muscle
            })
        except Exception as e:
            print(f"Error in summary route: {str(e)}")
            return jsonify({'error': str(e)}), 500

    # ============ EXERCISE BANK ROUTES ============
    @app.route('/coach/exercises', methods=['GET', 'POST'])
    def coach_exercises():
        """Liste et création des exercices"""
        forbidden = _require_coach()
        if forbidden:
            return forbidden

        if request.method == 'POST':
            name = (request.form.get('name') or '').strip()
            muscle_group = request.form.get('muscle_group', '').strip()
            
            if not name or not muscle_group:
                flash('Nom et groupe musculaire requis')
                return redirect(url_for('coach_exercises'))
            
            # Vérifier si l'exercice existe déjà
            existing = Exercise.query.filter_by(name=name).first()
            if existing:
                flash('Cet exercice existe déjà')
                return redirect(url_for('coach_exercises'))
            
            ex = Exercise(name=name, muscle_group=muscle_group)
            db.session.add(ex)
            db.session.commit()
            flash(f'Exercice "{name}" créé')
            return redirect(url_for('coach_exercises'))

        exercises = Exercise.query.order_by(Exercise.muscle_group, Exercise.name).all()
        return render_template('coach_exercises.html', exercises=exercises, muscle_groups=MUSCLE_GROUPS)

    @app.route('/coach/exercises/<int:exercise_id>/edit', methods=['GET', 'POST'])
    def coach_exercises_edit(exercise_id):
        """Édition d'un exercice"""
        forbidden = _require_coach()
        if forbidden:
            return forbidden

        from app.models import Exercise, MUSCLE_GROUPS
        ex = Exercise.query.get_or_404(exercise_id)

        if request.method == 'POST':
            name = (request.form.get('name') or '').strip()
            muscle_group = request.form.get('muscle_group', '').strip()
            
            if not name or not muscle_group:
                flash('Nom et groupe musculaire requis')
                return redirect(url_for('coach_exercises_edit', exercise_id=exercise_id))
            
            # Vérifier doublon (autre exercice avec le même nom)
            existing = Exercise.query.filter_by(name=name).first()
            if existing and existing.id != ex.id:
                flash('Un autre exercice a déjà ce nom')
                return redirect(url_for('coach_exercises_edit', exercise_id=exercise_id))
            
            ex.name = name
            ex.muscle_group = muscle_group
            db.session.commit()
            flash('Exercice mis à jour')
            return redirect(url_for('coach_exercises'))

        return render_template('coach_exercises_edit.html', exercise=ex, muscle_groups=MUSCLE_GROUPS)

    @app.route('/coach/exercises/<int:exercise_id>/delete', methods=['POST'])
    def coach_exercises_delete(exercise_id):
        """Suppression d'un exercice"""
        forbidden = _require_coach()
        if forbidden:
            return forbidden

        from app.models import Exercise
        ex = Exercise.query.get_or_404(exercise_id)
        name = ex.name
        db.session.delete(ex)
        db.session.commit()
        flash(f'Exercice "{name}" supprimé')
        return redirect(url_for('coach_exercises'))

    @app.route('/coach/exercises.json')
    def coach_exercises_json():
        """API pour récupérer les exercices (pour le select dynamique)"""
        if 'user_id' not in session:
            return jsonify({'error': 'not authenticated'}), 401
        
        user = User.query.get(session['user_id'])
        if not user or user.role != 'coach':
            return jsonify({'error': 'forbidden'}), 403
        
        exercises = Exercise.query.order_by(Exercise.name).all()
        return jsonify([ex.to_dict() for ex in exercises])

    # ===== ALIMENTS (Food) ROUTES =====
    
    @app.route('/coach/foods', methods=['GET', 'POST'])
    def coach_foods():
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or user.role != 'coach':
            flash('Accès réservé aux coachs')
            return redirect(url_for('home'))
        
        if request.method == 'POST':
            try:
                from app.models import Food
                name = request.form.get('name', '').strip()
                kcal = float(request.form.get('kcal', 0))
                proteins = float(request.form.get('proteins', 0))
                lipids = float(request.form.get('lipids', 0))
                carbs = float(request.form.get('carbs', 0))
                saturated_fats = request.form.get('saturated_fats')
                simple_sugars = request.form.get('simple_sugars')
                fiber = request.form.get('fiber')
                salt = request.form.get('salt')
                
                saturated_fats = float(saturated_fats) if saturated_fats else None
                simple_sugars = float(simple_sugars) if simple_sugars else None
                fiber = float(fiber) if fiber else None
                salt = float(salt) if salt else None
                
                if not name or kcal <= 0 or proteins < 0 or lipids < 0 or carbs < 0:
                    flash('Erreur: vérifiez les champs obligatoires')
                    return redirect(url_for('coach_foods'))
                
                existing = Food.query.filter_by(name=name).first()
                if existing:
                    flash(f'Aliment "{name}" existe déjà')
                    return redirect(url_for('coach_foods'))
                
                food = Food(
                    name=name,
                    kcal=kcal,
                    proteins=proteins,
                    lipids=lipids,
                    carbs=carbs,
                    saturated_fats=saturated_fats,
                    simple_sugars=simple_sugars,
                    fiber=fiber,
                    salt=salt
                )
                db.session.add(food)
                db.session.commit()
                flash(f'Aliment "{name}" créé')
                return redirect(url_for('coach_foods'))
            except Exception as e:
                flash(f'Erreur: {str(e)}')
                return redirect(url_for('coach_foods'))
        
        from app.models import Food
        foods = Food.query.order_by(Food.name).all()
        return render_template('coach_foods.html', foods=foods)

    @app.route('/coach/foods/<int:food_id>/edit', methods=['GET', 'POST'])
    def coach_foods_edit(food_id):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or user.role != 'coach':
            flash('Accès réservé aux coachs')
            return redirect(url_for('home'))
        
        from app.models import Food
        food = Food.query.get_or_404(food_id)
        
        if request.method == 'POST':
            try:
                food.name = request.form.get('name', '').strip()
                food.kcal = float(request.form.get('kcal', 0))
                food.proteins = float(request.form.get('proteins', 0))
                food.lipids = float(request.form.get('lipids', 0))
                food.carbs = float(request.form.get('carbs', 0))
                
                saturated_fats = request.form.get('saturated_fats')
                simple_sugars = request.form.get('simple_sugars')
                fiber = request.form.get('fiber')
                salt = request.form.get('salt')
                
                food.saturated_fats = float(saturated_fats) if saturated_fats else None
                food.simple_sugars = float(simple_sugars) if simple_sugars else None
                food.fiber = float(fiber) if fiber else None
                food.salt = float(salt) if salt else None
                
                if not food.name or food.kcal <= 0 or food.proteins < 0 or food.lipids < 0 or food.carbs < 0:
                    flash('Erreur: vérifiez les champs obligatoires')
                    return redirect(url_for('coach_foods_edit', food_id=food_id))
                
                db.session.commit()
                flash(f'Aliment "{food.name}" mis à jour')
                return redirect(url_for('coach_foods_edit', food_id=food_id))
            except Exception as e:
                flash(f'Erreur: {str(e)}')
                return redirect(url_for('coach_foods_edit', food_id=food_id))
        
        return render_template('coach_foods_edit.html', food=food)

    @app.route('/coach/foods/<int:food_id>/delete', methods=['POST'])
    def coach_foods_delete(food_id):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or user.role != 'coach':
            forbidden = False
            return forbidden

        from app.models import Food
        food = Food.query.get_or_404(food_id)
        name = food.name
        db.session.delete(food)
        db.session.commit()
        flash(f'Aliment "{name}" supprimé')
        return redirect(url_for('coach_foods'))

    @app.route('/seed-exercises')
    def seed_exercises_page():
        """Page to seed exercises"""
        forbidden = _require_coach()
        if forbidden:
            return forbidden
        return render_template('seed_exercises.html')

    @app.route('/admin/seed-exercises', methods=['POST'])
    def admin_seed_exercises():
        """Admin route to seed exercise database - requires coach role"""
        if 'user_id' not in session:
            return jsonify({'error': 'not authenticated'}), 401
        
        user = User.query.get(session['user_id'])
        if not user or user.role != 'coach':
            return jsonify({'error': 'forbidden'}), 403
        
        # Exercise data to insert
        exercises_data = [
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
        
        inserted = 0
        skipped = 0
        errors = []
        
        for name, muscle_group in exercises_data:
            # Check if exercise already exists
            existing = Exercise.query.filter_by(name=name).first()
            if existing:
                skipped += 1
            else:
                try:
                    exercise = Exercise(name=name, muscle_group=muscle_group)
                    db.session.add(exercise)
                    inserted += 1
                except Exception as e:
                    errors.append(f"Error for {name}: {str(e)}")
        
        try:
            db.session.commit()
            return jsonify({
                'success': True,
                'inserted': inserted,
                'skipped': skipped,
                'errors': errors,
                'message': f'Succès! {inserted} exercices insérés, {skipped} existants'
            }), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.context_processor
    def inject_now():
        # expose now() utilisable dans les templates : {{ now().date() }} ou {{ now().isoformat() }}
        return {'now': datetime.utcnow}

    @app.context_processor
    def coach_nav_static():
        items = {
            'availability': {'url': '/coach/availability', 'endpoint': 'coach_availability', 'label': 'Saisie availability'},
            # l'onglet "Création utilisateur" utilise la route /coach (page principale coach)
            'create_user' : {'url': '/coach',               'endpoint': 'coach',              'label': 'Création utilisateur'},
            'programming' : {'url': '/coach/programming',  'endpoint': 'coach_programming',  'label': 'Création programmation'},
            'exercises'   : {'url': '/coach/exercises',    'endpoint': 'coach_exercises',    'label': 'Banque d\'exercices'},
            'stats'       : {'url': '/coach/stats',         'endpoint': 'coach_stats',        'label': 'Suivi journal'},
            'meal_plan'   : {'url': '/coach/meal-plan',    'endpoint': 'coach_meal_plan',    'label': 'Plan alimentaire'},
        }
        return {'coach_nav_items_static': items}


def _to_float_none(val):
    if val is None or val == '':
        return None
    try:
        return float(val)
    except Exception:
        return None
