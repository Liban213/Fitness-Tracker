import sqlite3
from datetime import date
from functools import wraps

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

DATABASE = "repwise.db"

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-me"  # TODO: move to an env var


# ---------- Database helpers ----------

def get_db():
    """Open one connection per request and store it on Flask's g object."""
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
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


# ---------- Routes ----------

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
    user = get_db().execute(
        "SELECT username FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()
    if user is None:
        # The session points at a user that no longer exists (e.g. DB was reset).
        session.clear()
        return redirect(url_for("login"))

    # Only ever select workouts belonging to the logged-in user.
    workouts = get_db().execute(
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
    return render_template("dashboard.html", username=user["username"], workouts=workouts)


# ---------- Workouts ----------

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


@app.route("/workouts/new", methods=["GET", "POST"])
@login_required
def new_workout():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        workout_date = request.form.get("date", "").strip()

        if not name:
            flash("Workout name is required.", "error")
            return render_template("new_workout.html", name=name, date=workout_date)
        try:
            date.fromisoformat(workout_date)  # validates YYYY-MM-DD
        except ValueError:
            flash("Please enter a valid date.", "error")
            return render_template("new_workout.html", name=name, date=workout_date)

        db = get_db()
        cursor = db.execute(
            "INSERT INTO workouts (user_id, name, date) VALUES (?, ?, ?)",
            (session["user_id"], name, workout_date),
        )
        db.commit()
        flash("Workout created. Now add some exercises.", "success")
        return redirect(url_for("view_workout", workout_id=cursor.lastrowid))

    return render_template("new_workout.html", date=date.today().isoformat())


@app.route("/workouts/<int:workout_id>")
@login_required
def view_workout(workout_id):
    workout = get_own_workout(workout_id)
    exercises = get_db().execute(
        "SELECT * FROM exercises WHERE workout_id = ? ORDER BY id", (workout_id,)
    ).fetchall()
    return render_template("workout.html", workout=workout, exercises=exercises, form={})


@app.route("/workouts/<int:workout_id>/exercises", methods=["POST"])
@login_required
def add_exercise(workout_id):
    workout = get_own_workout(workout_id)  # ownership check before writing
    form = request.form
    name = form.get("name", "").strip()

    # Validate input: name required, sets/reps positive whole numbers,
    # weight optional but must be a non-negative number if given.
    error = None
    try:
        sets = int(form.get("sets", ""))
        reps = int(form.get("reps", ""))
        weight_text = form.get("weight", "").strip()
        weight = float(weight_text) if weight_text else None
    except ValueError:
        error = "Sets and reps must be whole numbers, and weight must be a number."
    else:
        if not name:
            error = "Exercise name is required."
        elif sets < 1 or reps < 1:
            error = "Sets and reps must be at least 1."
        elif weight is not None and weight < 0:
            error = "Weight can't be negative."

    if error:
        flash(error, "error")
        exercises = get_db().execute(
            "SELECT * FROM exercises WHERE workout_id = ? ORDER BY id", (workout_id,)
        ).fetchall()
        return render_template("workout.html", workout=workout, exercises=exercises, form=form)

    db = get_db()
    db.execute(
        "INSERT INTO exercises (workout_id, name, sets, reps, weight) VALUES (?, ?, ?, ?, ?)",
        (workout_id, name, sets, reps, weight),
    )
    db.commit()
    flash(f"Added {name}.", "success")
    return redirect(url_for("view_workout", workout_id=workout_id))


init_db()

if __name__ == "__main__":
    app.run(debug=True)
