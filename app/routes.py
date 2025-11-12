from flask import render_template, request, redirect, url_for, flash, session, abort, jsonify
from werkzeug.routing import BuildError
from app import app, db
from app.models import User, JournalEntry, PerformanceEntry, ProgramSession, Availability, Program
from datetime import date, datetime, timedelta

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
        if user and user.check_password(password):
            session.permanent = True
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash('Connecté')

            if user.username == 'admin' or user.role == 'coach':
                resp = redirect(url_for('coach'))
            else:
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
        # Form fields format: session_name_<day>, and for exercises arrays: ex_name_<day>[], ex_sets_<day>[], etc.
        # Clean old -- delete using ORM so SQLAlchemy applique la cascade et supprime les ExerciseEntry liées
        old_sessions = ProgramSession.query.filter_by(program_id=prog.id).all()
        for s in old_sessions:
            db.session.delete(s)
        db.session.flush()

        for day in range(7):
            sess_name = request.form.get(f'session_name_{day}', '').strip()
            # exercises come as lists (maybe empty)
            ex_names = request.form.getlist(f'ex_name_{day}[]')
            ex_sets = request.form.getlist(f'ex_sets_{day}[]')
            ex_reps = request.form.getlist(f'ex_reps_{day}[]')
            ex_rest = request.form.getlist(f'ex_rest_{day}[]')
            ex_rir = request.form.getlist(f'ex_rir_{day}[]')
            ex_inten = request.form.getlist(f'ex_int_{day}[]')
            ex_musc = request.form.getlist(f'ex_musc_{day}[]')
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
                    ee = ExerciseEntry(
                        session_id=ps.id,
                        position=position,
                        name=name,
                        sets=int(ex_sets[idx]) if ex_sets and idx < len(ex_sets) and ex_sets[idx].isdigit() else None,
                        reps=(ex_reps[idx] if idx < len(ex_reps) else None),
                        rest=(ex_rest[idx] if idx < len(ex_rest) else None),
                        rir=(ex_rir[idx] if idx < len(ex_rir) else None),
                        intensification=(ex_inten[idx] if idx < len(ex_inten) else None),
                        muscle=(ex_musc[idx] if idx < len(ex_musc) else None),
                        remark=(ex_rem[idx] if idx < len(ex_rem) else None)
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

        sets = None
        try:
            s = request.form.get('sets')
            sets = int(s) if s not in (None,'') else None
        except Exception:
            sets = None
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
            sets=sets,
            reps=reps,
            load=load,
            notes=notes
        )
        db.session.add(pe)
        db.session.commit()
        flash('Performance enregistrée')
        return redirect(url_for('athlete_performance_session', session_id=session_id))

    # GET : lister exercices de la séance (ProgramSession.exercises) et les performances liées (tri décroissant)
    session_exercises = [e.name for e in sorted(ps.exercises, key=lambda x: x.position)]
    perf_entries = PerformanceEntry.query.filter_by(athlete_id=user.id, program_session_id=ps.id).order_by(PerformanceEntry.entry_date.desc(), PerformanceEntry.created_at.desc()).all()
    return render_template('athlete_performance_session.html', athlete=user, program_session=ps, session_exercises=session_exercises, perf_entries=perf_entries)

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
        'sets': e.sets,
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
        s = request.form.get('sets')
        e.sets = int(s) if s not in (None,'') else None
    except Exception:
        e.sets = None
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
    total_sets = sum(e.sets or 0 for e in entries)
    total_reps = sum((e.reps or 0) * (e.sets or 1) for e in entries)
    total_volume = sum((e.load or 0) * (e.reps or 0) * (e.sets or 1) for e in entries)

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
    # gather performance entries for athlete, grouped by exercise and session date
    entries = PerformanceEntry.query.filter_by(athlete_id=athlete_id).order_by(PerformanceEntry.entry_date.asc()).all()
    payload = {}
    for e in entries:
        ex = e.exercise or 'Autre'
        d = e.entry_date.isoformat()
        if ex not in payload:
            payload[ex] = {}
        if d not in payload[ex]:
            payload[ex][d] = []
        payload[ex][d].append({
            'sets': e.sets,
            'reps': e.reps,
            'load': e.load,
            'notes': e.notes,
            'session_id': e.program_session_id
        })
    # convert to a friendly structure: { exercise: [ { date, avg_load, avg_reps, total_sets, count } ... ] }
    out = {}
    for ex, bydate in payload.items():
        series = []
        for d in sorted(bydate.keys()):
            items = bydate[d]
            avg_load = sum((it.get('load') or 0) for it in items) / (len(items) or 1)
            avg_reps = sum((it.get('reps') or 0) for it in items) / (len(items) or 1)
            total_sets = sum((it.get('sets') or 0) for it in items)
            series.append({'date': d, 'avg_load': avg_load, 'avg_reps': avg_reps, 'total_sets': total_sets, 'count': len(items)})
        out[ex] = series
    return jsonify(out)

@app.context_processor
def inject_now():
    # expose now() utilisable dans les templates : {{ now().date() }} ou {{ now().isoformat() }}
    return {'now': datetime.utcnow}

def _to_float_none(val):
    if val is None or val == '':
        return None
    try:
        return float(val)
    except Exception:
        return None

@app.context_processor
def coach_nav_static():
    items = {
        'availability': {'url': '/coach/availability', 'endpoint': 'coach_availability', 'label': 'Saisie availability'},
        # l'onglet "Création utilisateur" utilise la route /coach (page principale coach)
        'create_user' : {'url': '/coach',               'endpoint': 'coach',              'label': 'Création utilisateur'},
        'programming' : {'url': '/coach/programming',  'endpoint': 'coach_programming',  'label': 'Création programmation'},
        'stats'       : {'url': '/coach/stats',         'endpoint': 'coach_stats',        'label': 'Suivi journal'},
    }
    return {'coach_nav_items_static': items}