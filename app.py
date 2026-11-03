import os
import sqlite3
from datetime import date, timedelta
from functools import wraps

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
# Set SECRET_KEY in the environment for any real deployment; the fallback is
# only for local development.
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
app.config["DATABASE"] = "repwise.db"


# ---------- Database helpers ----------

def get_db():
    """Open one connection per request and store it on Flask's g object."""
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row  # lets us access columns by name
    return g.db


@app.teardown_appcontext
def close_db(exception):
    """Close the connection automatically at the end of each request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create any missing tables (runs on startup, safe to run repeatedly)."""
    with app.app_context():
        db = get_db()
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );

            -- Each workout belongs to one user.
            CREATE TABLE IF NOT EXISTS workouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users (id),
                name TEXT NOT NULL,
                date TEXT NOT NULL  -- stored as YYYY-MM-DD
            );

            -- Each exercise belongs to one workout.
            CREATE TABLE IF NOT EXISTS exercises (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workout_id INTEGER NOT NULL REFERENCES workouts (id),
                name TEXT NOT NULL,
                sets INTEGER NOT NULL,
                reps INTEGER NOT NULL,
                weight REAL  -- optional (e.g. bodyweight exercises)
            );
            """
        )
        db.commit()


@app.template_filter("weight")
def format_weight(value):
    """Show weights without a pointless ".0" (60.0 -> "60", 22.5 -> "22.5")."""
    if not value and value != 0:
        return ""
    try:
        return f"{float(value):.2f}".rstrip("0").rstrip(".")
    except ValueError:
        return value  # not a number (e.g. bad form input) - show it as typed


# ---------- Auth helpers ----------

def login_required(view):
    """Redirect to /login if the user isn't logged in.

    A user counts as "logged in" when their user_id is stored in the session
    cookie, which Flask signs with app.secret_key so it can't be tampered with.
    """
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


# ---------- Auth routes ----------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Username and password are both required.", "error")
            return render_template("register.html", username=username)

        db = get_db()
        try:
            # Never store the plain password - only a salted hash of it.
            db.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, generate_password_hash(password)),
            )
            db.commit()
        except sqlite3.IntegrityError:
            # The UNIQUE constraint on username rejected a duplicate.
            flash("That username is already taken.", "error")
            return render_template("register.html", username=username)

        flash("Account created! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Username and password are both required.", "error")
            return render_template("login.html", username=username)

        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        # check_password_hash hashes the submitted password the same way and
        # compares it to the stored hash. We use one generic error message so
        # we don't reveal whether the username exists.
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid username or password.", "error")
            return render_template("login.html", username=username)

        # Success: remember who this is for future requests.
        session.clear()
        session["user_id"] = user["id"]
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    db = get_db()
    user = db.execute(
        "SELECT username FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()
    if user is None:
        # The session points at a user that no longer exists (e.g. DB was reset).
        session.clear()
        return redirect(url_for("login"))

    # Only ever select workouts belonging to the logged-in user.
    workouts = db.execute(
        """
        SELECT workouts.id, workouts.name, workouts.date, COUNT(exercises.id) AS exercise_count
        FROM workouts
        LEFT JOIN exercises ON exercises.workout_id = workouts.id
        WHERE workouts.user_id = ?
        GROUP BY workouts.id
        ORDER BY workouts.date DESC, workouts.id DESC
        """,
        (session["user_id"],),
    ).fetchall()

    # Every distinct exercise this user has logged, for the history links.
    # Grouping by LOWER(name) treats "Bench press" and "bench press" as one.
    exercise_names = db.execute(
        """
        SELECT MIN(exercises.name) AS name, COUNT(*) AS times_logged
        FROM exercises
        JOIN workouts ON workouts.id = exercises.workout_id
        WHERE workouts.user_id = ?
        GROUP BY LOWER(exercises.name)
        ORDER BY LOWER(exercises.name)
        """,
        (session["user_id"],),
    ).fetchall()

    # Numbers for the stat tiles at the top of the dashboard.
    week_start = date.today() - timedelta(days=date.today().weekday())  # this Monday
    week_end = week_start + timedelta(days=6)
    stats = {
        "workouts": len(workouts),
        "exercises": sum(workout["exercise_count"] for workout in workouts),
        "this_week": sum(
            1 for workout in workouts
            if week_start.isoformat() <= workout["date"] <= week_end.isoformat()
        ),
    }

    return render_template(
        "dashboard.html",
        username=user["username"],
        workouts=workouts,
        exercise_names=exercise_names,
        stats=stats,
    )


# ---------- Ownership + validation helpers ----------

def get_own_workout(workout_id):
    """Fetch a workout, but only if it belongs to the logged-in user.

    Filtering by user_id as well as id stops someone from viewing another
    user's workout just by changing the number in the URL.
    """
    workout = get_db().execute(
        "SELECT * FROM workouts WHERE id = ? AND user_id = ?",
        (workout_id, session["user_id"]),
    ).fetchone()
    if workout is None:
        abort(404)
    return workout


def get_own_exercise(exercise_id):
    """Fetch an exercise, but only if its workout belongs to the logged-in user.

    Exercises don't store a user_id themselves, so we join to their workout
    to check who owns them.
    """
    exercise = get_db().execute(
        """
        SELECT exercises.*
        FROM exercises
        JOIN workouts ON workouts.id = exercises.workout_id
        WHERE exercises.id = ? AND workouts.user_id = ?
        """,
        (exercise_id, session["user_id"]),
    ).fetchone()
    if exercise is None:
        abort(404)
    return exercise


def get_exercises(workout_id):
    return get_db().execute(
        "SELECT * FROM exercises WHERE workout_id = ? ORDER BY id", (workout_id,)
    ).fetchall()


def validate_workout(form):
    """Check a submitted workout form. Returns (error, name, date)."""
    name = form.get("name", "").strip()
    workout_date = form.get("date", "").strip()

    if not name:
        return "Workout name is required.", name, workout_date
    try:
        date.fromisoformat(workout_date)  # validates YYYY-MM-DD
    except ValueError:
        return "Please enter a valid date.", name, workout_date
    return None, name, workout_date


def validate_exercise(form):
    """Check a submitted exercise form. Returns (error, values).

    Rules: name required, sets/reps whole numbers >= 1, weight optional
    but must be a non-negative number if given.
    """
    name = form.get("name", "").strip()
    try:
        sets = int(form.get("sets", ""))
        reps = int(form.get("reps", ""))
        weight_text = form.get("weight", "").strip()
        weight = float(weight_text) if weight_text else None
    except ValueError:
        return "Sets and reps must be whole numbers, and weight must be a number.", None

    if not name:
        return "Exercise name is required.", None
    if sets < 1 or reps < 1:
        return "Sets and reps must be at least 1.", None
    if weight is not None and weight < 0:
        return "Weight can't be negative.", None
    return None, {"name": name, "sets": sets, "reps": reps, "weight": weight}


# ---------- Workout routes ----------

@app.route("/workouts/new", methods=["GET", "POST"])
@login_required
def new_workout():
    form_page = {"heading": "New workout", "button": "Create workout", "cancel_url": url_for("dashboard")}

    if request.method == "POST":
        error, name, workout_date = validate_workout(request.form)
        if error:
            flash(error, "error")
            return render_template("workout_form.html", name=name, date=workout_date, **form_page)

        db = get_db()
        cursor = db.execute(
            "INSERT INTO workouts (user_id, name, date) VALUES (?, ?, ?)",
            (session["user_id"], name, workout_date),
        )
        db.commit()
        flash("Workout created. Now add some exercises.", "success")
        return redirect(url_for("view_workout", workout_id=cursor.lastrowid))

    return render_template("workout_form.html", date=date.today().isoformat(), **form_page)


@app.route("/workouts/<int:workout_id>")
@login_required
def view_workout(workout_id):
    workout = get_own_workout(workout_id)
    return render_template("workout.html", workout=workout, exercises=get_exercises(workout_id), form={})


@app.route("/workouts/<int:workout_id>/edit", methods=["GET", "POST"])
@login_required
def edit_workout(workout_id):
    workout = get_own_workout(workout_id)  # ownership check before showing or saving
    form_page = {
        "heading": "Edit workout",
        "button": "Save changes",
        "cancel_url": url_for("view_workout", workout_id=workout_id),
    }

    if request.method == "POST":
        error, name, workout_date = validate_workout(request.form)
        if error:
            flash(error, "error")
            return render_template("workout_form.html", name=name, date=workout_date, **form_page)

        db = get_db()
        db.execute(
            "UPDATE workouts SET name = ?, date = ? WHERE id = ?", (name, workout_date, workout_id)
        )
        db.commit()
        flash("Workout updated.", "success")
        return redirect(url_for("view_workout", workout_id=workout_id))

    return render_template("workout_form.html", name=workout["name"], date=workout["date"], **form_page)


# Deleting uses POST (a form button), never GET (a plain link), so a workout
# can't be deleted just by someone visiting or prefetching a URL.
@app.route("/workouts/<int:workout_id>/delete", methods=["POST"])
@login_required
def delete_workout(workout_id):
    workout = get_own_workout(workout_id)
    db = get_db()
    # Delete the workout's exercises first so none are left pointing at a
    # workout that no longer exists. Both deletes are committed together.
    db.execute("DELETE FROM exercises WHERE workout_id = ?", (workout_id,))
    db.execute("DELETE FROM workouts WHERE id = ?", (workout_id,))
    db.commit()
    flash(f"Deleted {workout['name']}.", "success")
    return redirect(url_for("dashboard"))


# ---------- Exercise routes ----------

@app.route("/workouts/<int:workout_id>/exercises", methods=["POST"])
@login_required
def add_exercise(workout_id):
    workout = get_own_workout(workout_id)  # ownership check before writing
    error, values = validate_exercise(request.form)
    if error:
        flash(error, "error")
        return render_template(
            "workout.html", workout=workout, exercises=get_exercises(workout_id), form=request.form
        )

    db = get_db()
    db.execute(
        "INSERT INTO exercises (workout_id, name, sets, reps, weight) VALUES (?, ?, ?, ?, ?)",
        (workout_id, values["name"], values["sets"], values["reps"], values["weight"]),
    )
    db.commit()
    flash(f"Added {values['name']}.", "success")
    return redirect(url_for("view_workout", workout_id=workout_id))


@app.route("/exercises/<int:exercise_id>/edit", methods=["GET", "POST"])
@login_required
def edit_exercise(exercise_id):
    exercise = get_own_exercise(exercise_id)

    if request.method == "POST":
        error, values = validate_exercise(request.form)
        if error:
            flash(error, "error")
            return render_template("exercise_form.html", exercise=exercise, form=request.form)

        db = get_db()
        db.execute(
            "UPDATE exercises SET name = ?, sets = ?, reps = ?, weight = ? WHERE id = ?",
            (values["name"], values["sets"], values["reps"], values["weight"], exercise_id),
        )
        db.commit()
        flash("Exercise updated.", "success")
        return redirect(url_for("view_workout", workout_id=exercise["workout_id"]))

    return render_template("exercise_form.html", exercise=exercise, form=exercise)


@app.route("/exercises/<int:exercise_id>/delete", methods=["POST"])
@login_required
def delete_exercise(exercise_id):
    exercise = get_own_exercise(exercise_id)
    db = get_db()
    db.execute("DELETE FROM exercises WHERE id = ?", (exercise_id,))
    db.commit()
    flash(f"Deleted {exercise['name']}.", "success")
    return redirect(url_for("view_workout", workout_id=exercise["workout_id"]))


@app.route("/history")
@login_required
def exercise_history():
    """Every time the user has logged one exercise, plus their best weight."""
    name = request.args.get("exercise", "").strip()
    if not name:
        return redirect(url_for("dashboard"))

    # Match names case-insensitively, and only within this user's workouts.
    entries = get_db().execute(
        """
        SELECT exercises.*, workouts.name AS workout_name, workouts.date
        FROM exercises
        JOIN workouts ON workouts.id = exercises.workout_id
        WHERE workouts.user_id = ? AND LOWER(exercises.name) = LOWER(?)
        ORDER BY workouts.date DESC, exercises.id DESC
        """,
        (session["user_id"], name),
    ).fetchall()

    # Personal record = the heaviest weight logged (bodyweight entries skipped).
    weighted = [entry for entry in entries if entry["weight"] is not None]
    record = max(weighted, key=lambda entry: entry["weight"]) if weighted else None

    return render_template("history.html", name=name, entries=entries, record=record)


init_db()

if __name__ == "__main__":
    app.run(debug=True)
