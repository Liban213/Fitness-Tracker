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

To run the automated tests (they use a temporary database, not `repwise.db`):

```bash
pytest
```

For anything beyond local development, set a real secret key first:

```bash
export SECRET_KEY="some-long-random-string"
```

The SQLite database (`repwise.db`) is created automatically on first run.

## Project structure

```
app.py              Routes and database logic (plain sqlite3, no ORM)
templates/          Jinja2 templates (base, auth pages, dashboard, workouts, history)
static/style.css    Styling
test_app.py         Automated tests (pytest)
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

## Sprint 3: edit, delete + exercise history

- Edit a workout (`/workouts/<id>/edit`) or an exercise (`/exercises/<id>/edit`)
- Delete a workout (and its exercises) or a single exercise, with a confirmation
  prompt; deletes are POST-only so visiting a URL can't delete anything
- Exercise history (`/history?exercise=<name>`): every time you've logged an
  exercise (case-insensitive), plus your personal record (heaviest weight)
- Dashboard lists each exercise you've logged with a link to its history
- Same ownership rules as Sprint 2: other users' workouts/exercises return 404
- `SECRET_KEY` is read from an environment variable (dev fallback for local use)
- Weights display without a trailing `.0` (60 instead of 60.0)
- 39 automated tests in `test_app.py` covering Sprints 1–3

**Not yet built:** progress charts, workout plans/templates, account settings.

## Known limitations

- Forms have no CSRF protection yet (Flask-WTF would add this).
