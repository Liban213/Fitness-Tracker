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
templates/          Jinja2 templates (base, auth pages, dashboard, workouts)
static/style.css    Styling
requirements.txt    Python dependencies
```

## Sprint 1: auth + skeleton (done)

- User registration (passwords hashed with `werkzeug.security`)
- Login / logout using Flask sessions
- `login_required` decorator protecting the dashboard
- Input validation (no empty username/password) and flash messages

## Sprint 2: workouts + exercise logging

- New `workouts` table (`id`, `user_id`, `name`, `date`) and `exercises` table
  (`id`, `workout_id`, `name`, `sets`, `reps`, `weight`), created automatically
  on startup (existing databases get the new tables too)
- `GET/POST /workouts/new`: create a workout (name + date)
- `GET /workouts/<id>`: view a workout and its exercises
- `POST /workouts/<id>/exercises`: log an exercise (sets, reps, optional weight in kg)
- Dashboard lists your workouts, newest first, with an exercise count
- Every query is scoped to the logged-in user; another user's workout returns 404
- Validation: required names, valid date, sets/reps >= 1, weight >= 0

**Not yet built:** editing or deleting workouts/exercises, progress charts, workout plans/templates.

## Known TODOs

- `app.secret_key` is a hard-coded placeholder; move it to an environment variable.
