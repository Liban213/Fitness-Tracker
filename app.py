import sqlite3
from functools import wraps

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
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
    """Create the users table if it doesn't exist yet (runs on startup)."""
    with app.app_context():
        db = get_db()
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
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
    return render_template("dashboard.html", username=user["username"])


init_db()

if __name__ == "__main__":
    app.run(debug=True)
