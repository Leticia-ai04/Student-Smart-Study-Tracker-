import os
import sqlite3
from flask import Flask, render_template, request, redirect, session, url_for, flash, Response, jsonify, g, send_file
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from textblob import TextBlob
from datetime import datetime, timedelta
import random
import io
from fpdf import FPDF
from flask_socketio import SocketIO, emit
from flask import Flask, send_from_directory

app = Flask(__name__)
app.secret_key = 'student_secret'
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

socketio = SocketIO(app)
chat_messages = []

LANGUAGES = {'en': 'English', 'sw': 'Swahili'}

def init_db():
    with sqlite3.connect("student_tracker.db") as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT, email TEXT, password TEXT,
                        profile_pic TEXT, points INTEGER DEFAULT 0, badge TEXT DEFAULT 'Newbie')''')
        c.execute('''CREATE TABLE IF NOT EXISTS study_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER, subject TEXT, duration INTEGER,
                        mood TEXT, date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER, task TEXT, due_date TEXT, completed INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS journal (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER, content TEXT, entry_date TEXT, sentiment TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS resources (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER, title TEXT, file_path TEXT,
                        uploaded_on TEXT)''')
init_db()

def update_points_and_badge(user_id, points_to_add):
    with sqlite3.connect("student_tracker.db") as conn:
        c = conn.cursor()
        c.execute("SELECT points FROM users WHERE id=?", (user_id,))
        points = c.fetchone()
        if points is None:
            return
        points = points[0] + points_to_add
        badge = 'Newbie'
        if points > 100: badge = 'Achiever'
        if points > 300: badge = 'Champion'
        if points > 500: badge = 'Legend'
        c.execute("UPDATE users SET points=?, badge=? WHERE id=?", (points, badge, user_id))
        conn.commit()

@app.before_request
def before_request():
    g.lang = session.get('lang', 'en')

@app.route('/service-worker.js')
def service_worker():
    return send_from_directory('static', 'service-worker.js')

@app.context_processor
def inject_now():
    return {'now': datetime.now()}

@app.route('/')
def home():
    return redirect('/login')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        file = request.files.get('profile_pic')
        filename = ''
        if file and file.filename:
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        hashed_password = generate_password_hash(password)
        with sqlite3.connect("student_tracker.db") as conn:
            c = conn.cursor()
            c.execute("INSERT INTO users (username, email, password, profile_pic) VALUES (?, ?, ?, ?)",
                      (username, email, hashed_password, filename))
            conn.commit()
        return redirect('/login')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        with sqlite3.connect("student_tracker.db") as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE email=?", (email,))
            user = c.fetchone()
            if user and check_password_hash(user[3], password):
                session['user_id'] = user[0]
                return redirect('/dashboard')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    user = None
    sessions = []
    tasks = []
    upcoming_tasks = []
    chart_labels = []
    chart_data = []
    quote = random.choice([
        "Success is the sum of small efforts, repeated day in and day out.",
        "The secret of getting ahead is getting started.",
        "Don’t watch the clock; do what it does. Keep going.",
        "Great things never come from comfort zones.",
        "Push yourself, because no one else is going to do it for you."
    ])
    due_today = []
    if 'user_id' in session:
        with sqlite3.connect("student_tracker.db") as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE id=?", (session['user_id'],))
            user = c.fetchone()
            c.execute("SELECT * FROM study_sessions WHERE user_id=?", (session['user_id'],))
            sessions = c.fetchall()
            c.execute("SELECT * FROM tasks WHERE user_id=?", (session['user_id'],))
            tasks = c.fetchall()
            today = datetime.now().date()
            next_week = today + timedelta(days=7)
            c.execute("SELECT * FROM tasks WHERE user_id=? AND due_date BETWEEN ? AND ?", (session['user_id'], today.strftime('%Y-%m-%d'), next_week.strftime('%Y-%m-%d')))
            upcoming_tasks = c.fetchall()
            c.execute("SELECT * FROM tasks WHERE user_id=? AND due_date=?", (session['user_id'], today.strftime('%Y-%m-%d')))
            due_today = c.fetchall()
            chart_labels = []
            chart_data = []
            for i in range(6, -1, -1):
                day = today - timedelta(days=i)
                chart_labels.append(day.strftime('%a'))
                c.execute("SELECT SUM(duration) FROM study_sessions WHERE user_id=? AND date=?", (session['user_id'], day.strftime('%Y-%m-%d')))
                total = c.fetchone()[0] or 0
                chart_data.append(total)
    if not user:
        return redirect('/login')
    return render_template('dashboard.html', user=user, sessions=sessions, tasks=tasks,
                           upcoming_tasks=upcoming_tasks, chart_labels=chart_labels, chart_data=chart_data, quote=quote, due_today=due_today)

@app.route('/add_session', methods=['POST'])
def add_session():
    if 'user_id' in session:
        subject = request.form.get('subject', '').strip()
        duration = request.form.get('duration', '0').strip()
        date = datetime.now().strftime('%Y-%m-%d')
        with sqlite3.connect("student_tracker.db") as conn:
            c = conn.cursor()
            c.execute("INSERT INTO study_sessions (user_id, subject, duration, mood, date) VALUES (?, ?, ?, '', ?)",
                      (session['user_id'], subject, duration, date))
            conn.commit()
        update_points_and_badge(session['user_id'], int(duration))
    return redirect('/dashboard')

@app.route('/add_task', methods=['POST'])
def add_task():
    if 'user_id' in session:
        task = request.form.get('task', '').strip()
        due_date = request.form.get('due_date', '').strip()
        with sqlite3.connect("student_tracker.db") as conn:
            c = conn.cursor()
            c.execute("INSERT INTO tasks (user_id, task, due_date, completed) VALUES (?, ?, ?, 0)",
                      (session['user_id'], task, due_date))
            conn.commit()
        update_points_and_badge(session['user_id'], 10)
    return redirect('/dashboard')

@app.route('/add_journal_dashboard', methods=['POST'])
def add_journal_dashboard():
    if 'user_id' in session:
        entry = request.form.get('entry', '').strip()
        date = datetime.now().strftime('%Y-%m-%d')
        sentiment = 'Neutral'
        if entry:
            blob = TextBlob(entry)
            polarity = blob.sentiment.polarity
            if polarity > 0.2: sentiment = 'Positive'
            elif polarity < -0.2: sentiment = 'Negative'
        with sqlite3.connect("student_tracker.db") as conn:
            c = conn.cursor()
            c.execute("INSERT INTO journal (user_id, content, entry_date, sentiment) VALUES (?, ?, ?, ?)",
                      (session['user_id'], entry, date, sentiment))
            conn.commit()
        update_points_and_badge(session['user_id'], 5)
    return redirect('/dashboard')

# Fix for BuildError: correct endpoint names
@app.route('/journal', methods=['GET', 'POST'])
def journal():
    journal_entries = []
    if 'user_id' in session:
        with sqlite3.connect("student_tracker.db") as conn:
            c = conn.cursor()
            if request.method == 'POST':
                entry = request.form.get('entry', '').strip()
                date = datetime.now().strftime('%Y-%m-%d')
                sentiment = 'Neutral'
                if entry:
                    blob = TextBlob(entry)
                    polarity = blob.sentiment.polarity
                    if polarity > 0.2:
                        sentiment = 'Positive'
                    elif polarity < -0.2:
                        sentiment = 'Negative'
                c.execute("INSERT INTO journal (user_id, content, entry_date, sentiment) VALUES (?, ?, ?, ?)",
                          (session['user_id'], entry, date, sentiment))
                conn.commit()
                update_points_and_badge(session['user_id'], 5)
            c.execute("SELECT id, content, entry_date, sentiment FROM journal WHERE user_id=?", (session['user_id'],))
            journal_entries = c.fetchall()
    else:
        return redirect('/login')

    journal_dicts = []
    for j in journal_entries:
        journal_dicts.append({
            'id': j[0],
            'entry': j[1],
            'date': j[2],
            'sentiment': j[3]
        })

    return render_template('journal.html', journal=journal_dicts)

@app.route('/export_journal')
def export_journal():
    if 'user_id' not in session:
        return redirect('/login')

    with sqlite3.connect("student_tracker.db") as conn:
        c = conn.cursor()
        c.execute("SELECT content, entry_date, sentiment FROM journal WHERE user_id=?", (session['user_id'],))
        entries = c.fetchall()

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="My Journal Entries", ln=True, align='C')
    pdf.ln(10)

    for content, entry_date, sentiment in entries:
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(0, 8, f"Date: {entry_date} | Sentiment: {sentiment}", ln=True)
        pdf.set_font("Arial", '', 10)
        pdf.multi_cell(0, 8, content)
        pdf.ln(5)

    pdf_output = pdf.output(dest='S').encode('latin1')

    return Response(pdf_output, mimetype='application/pdf',
                    headers={"Content-Disposition": "attachment;filename=journal_entries.pdf"})

@app.route('/resources', methods=['GET', 'POST'])
def resources():
    resources = []
    if 'user_id' in session:
        with sqlite3.connect("student_tracker.db") as conn:
            c = conn.cursor()
            if request.method == 'POST':
                title = request.form.get('title', '').strip()
                file = request.files.get('file')
                filename = ''
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                c.execute("INSERT INTO resources (user_id, title, file_path, uploaded_on) VALUES (?, ?, ?, '')",
                          (session['user_id'], title, filename))
                conn.commit()
                update_points_and_badge(session['user_id'], 10)
            c.execute("SELECT * FROM resources WHERE user_id=?", (session['user_id'],))
            resources = c.fetchall()
    return render_template('resources.html', resources=resources)

# --- Study Group Chat ---
@app.route('/chat')
def chat():
    if 'user_id' not in session:
        return redirect('/login')
    return render_template('chat.html', user_id=session['user_id'])

@socketio.on('send_message')
def handle_send_message(data):
    chat_messages.append({'user': data['user'], 'msg': data['msg']})
    emit('receive_message', data, broadcast=True)

# --- Admin Panel ---
@app.route('/admin')
def admin():
    if 'user_id' not in session:
        return redirect('/login')
    with sqlite3.connect("student_tracker.db") as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users")
        users = c.fetchall()
    return render_template('admin.html', users=users)

@app.route('/leaderboard')
def leaderboard():
    if 'user_id' not in session:
        return redirect('/login')
    with sqlite3.connect("student_tracker.db") as conn:
        c = conn.cursor()
        c.execute("SELECT username, points, badge FROM users ORDER BY points DESC")
        users = c.fetchall()
    return render_template('leaderboard.html', users=users)

# --- Mobile API Endpoints ---
@app.route('/api/sessions')
def api_sessions():
    if 'user_id' not in session:
        return jsonify({'error': 'not logged in'}), 401
    with sqlite3.connect("student_tracker.db") as conn:
        c = conn.cursor()
        c.execute("SELECT subject, duration, date FROM study_sessions WHERE user_id=?", (session['user_id'],))
        sessions = c.fetchall()
    return jsonify([{'subject': s[0], 'duration': s[1], 'date': s[2]} for s in sessions])

@app.route('/api/tasks')
def api_tasks():
    if 'user_id' not in session:
        return jsonify({'error': 'not logged in'}), 401
    with sqlite3.connect("student_tracker.db") as conn:
        c = conn.cursor()
        c.execute("SELECT task, due_date, completed FROM tasks WHERE user_id=?", (session['user_id'],))
        tasks = c.fetchall()
    return jsonify([{'task': t[0], 'due_date': t[1], 'completed': bool(t[2])} for t in tasks])

# --- Multi-language Support ---
@app.route('/set_lang/<lang>')
def set_lang(lang):
    if lang in LANGUAGES:
        session['lang'] = lang
    return redirect(request.referrer or '/dashboard')

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    user = None
    if 'user_id' in session:
        with sqlite3.connect("student_tracker.db") as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE id=?", (session['user_id'],))
            user = c.fetchone()
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            email = request.form.get('email', '').strip()
            file = request.files.get('profile_pic')
            filename = user[4]
            if file and file.filename:
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            with sqlite3.connect("student_tracker.db") as conn:
                c = conn.cursor()
                c.execute("UPDATE users SET username=?, email=?, profile_pic=? WHERE id=?",
                          (username, email, filename, user[0]))
                conn.commit()
            flash("Profile updated!")
            return redirect('/profile')
    if not user:
        return redirect('/login')
    return render_template('profile.html', user=user)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

if __name__ == '__main__':
    socketio.run(app, debug=True)
