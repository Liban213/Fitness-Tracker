# Repwise

A simple fitness/workout tracker built with Flask and SQLite.

## Setup

```bash
# 1. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app
python app.py
```

Then open http://127.0.0.1:5000 in your browser.

The SQLite database (`repwise.db`) is created automatically on first run.

## Project structure

```
app.py              Routes and database logic (plain sqlite3, no ORM)
templates/          Jinja2 templates (base, register, login, dashboard)
static/style.css    Styling
requirements.txt    Python dependencies
```

## Scope: Sprint 1, Week 3

**In scope this week (auth + skeleton):**
- User registration (passwords hashed with `werkzeug.security`)
- Login / logout using Flask sessions
- `login_required` decorator protecting the dashboard
- Bare dashboard showing "Logged in as {username}"
- Input validation (no empty username/password) and flash messages

**Out of scope (next week):**
- Workout plans
- Exercise logging
- Anything beyond auth and the bare dashboard

## Known TODOs

- `app.secret_key` is a hard-coded placeholder; move it to an environment variable.
