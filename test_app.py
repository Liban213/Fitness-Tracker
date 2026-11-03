"""Automated tests for Repwise. Run with:  pytest

Each test gets a fresh, empty database in a temporary folder, so tests never
touch repwise.db and can't affect each other.
"""
import pytest

from app import app, format_weight, init_db


@pytest.fixture
def client(tmp_path):
    app.config.update(TESTING=True, DATABASE=str(tmp_path / "test.db"))
    init_db()
    return app.test_client()


@pytest.fixture
def other_client(client):
    """A second, separately logged-in user (shares the same test database)."""
    other = app.test_client()
    register_and_login(other, "bob")
    return other


# ---------- Helpers ----------

def register_and_login(client, username="alice", password="secret"):
    client.post("/register", data={"username": username, "password": password})
    return client.post("/login", data={"username": username, "password": password})


def create_workout(client, name="Push day", date="2026-11-03"):
    response = client.post("/workouts/new", data={"name": name, "date": date})
    return int(response.location.rsplit("/", 1)[1])  # redirected to /workouts/<id>


def add_exercise(client, workout_id, name="Bench press", sets="3", reps="8", weight="60"):
    return client.post(
        f"/workouts/{workout_id}/exercises",
        data={"name": name, "sets": sets, "reps": reps, "weight": weight},
        follow_redirects=True,
    )


def first_exercise_id(workout_id):
    with app.app_context():
        from app import get_db
        return get_db().execute(
            "SELECT id FROM exercises WHERE workout_id = ? ORDER BY id", (workout_id,)
        ).fetchone()["id"]


# ---------- Sprint 1: auth ----------

def test_register_redirects_to_login(client):
    response = client.post("/register", data={"username": "alice", "password": "secret"})
    assert response.status_code == 302
    assert response.location == "/login"


def test_register_rejects_empty_fields(client):
    response = client.post("/register", data={"username": "  ", "password": ""})
    assert b"Username and password are both required." in response.data


def test_register_rejects_duplicate_username(client):
    client.post("/register", data={"username": "alice", "password": "secret"})
    response = client.post("/register", data={"username": "alice", "password": "other"})
    assert b"That username is already taken." in response.data


def test_password_is_stored_hashed(client):
    client.post("/register", data={"username": "alice", "password": "secret"})
    with app.app_context():
        from app import get_db
        stored = get_db().execute("SELECT password_hash FROM users").fetchone()["password_hash"]
    assert stored != "secret"


def test_login_success_shows_dashboard(client):
    register_and_login(client)
    assert b"Logged in as <strong>alice</strong>" in client.get("/").data


def test_login_wrong_password_and_unknown_user_give_same_error(client):
    client.post("/register", data={"username": "alice", "password": "secret"})
    wrong_password = client.post("/login", data={"username": "alice", "password": "nope"})
    unknown_user = client.post("/login", data={"username": "nobody", "password": "nope"})
    assert b"Invalid username or password." in wrong_password.data
    assert b"Invalid username or password." in unknown_user.data


def test_logout_locks_dashboard_again(client):
    register_and_login(client)
    client.get("/logout")
    assert client.get("/").location == "/login"


@pytest.mark.parametrize("url", ["/", "/workouts/new", "/workouts/1", "/history?exercise=Bench"])
def test_pages_require_login(client, url):
    assert client.get(url).location == "/login"


# ---------- Sprint 2: workouts + exercises ----------

def test_create_workout_and_list_on_dashboard(client):
    register_and_login(client)
    workout_id = create_workout(client)
    add_exercise(client, workout_id)
    dashboard = client.get("/").data
    assert b"Push day" in dashboard
    assert b"1 exercise" in dashboard


@pytest.mark.parametrize("data, error", [
    ({"name": "", "date": "2026-11-03"}, b"Workout name is required."),
    ({"name": "Legs", "date": "not-a-date"}, b"Please enter a valid date."),
])
def test_create_workout_validation(client, data, error):
    register_and_login(client)
    assert error in client.post("/workouts/new", data=data).data


@pytest.mark.parametrize("fields, error", [
    ({"name": ""}, b"Exercise name is required."),
    ({"sets": "0"}, b"Sets and reps must be at least 1."),
    ({"reps": "abc"}, b"must be whole numbers"),
    ({"weight": "-5"}, b"Weight can&#39;t be negative."),
])
def test_add_exercise_validation(client, fields, error):
    register_and_login(client)
    workout_id = create_workout(client)
    assert error in add_exercise(client, workout_id, **fields).data


def test_exercise_without_weight_shows_dash(client):
    register_and_login(client)
    workout_id = create_workout(client)
    response = add_exercise(client, workout_id, name="Pull-up", weight="")
    assert "<td>—</td>".encode() in response.data


# ---------- Sprint 3: edit + delete ----------

def test_edit_workout(client):
    register_and_login(client)
    workout_id = create_workout(client)
    client.post(f"/workouts/{workout_id}/edit", data={"name": "Pull day", "date": "2026-11-04"})
    page = client.get(f"/workouts/{workout_id}").data
    assert b"Pull day" in page and b"2026-11-04" in page


def test_edit_workout_validation(client):
    register_and_login(client)
    workout_id = create_workout(client)
    response = client.post(f"/workouts/{workout_id}/edit", data={"name": "", "date": "2026-11-04"})
    assert b"Workout name is required." in response.data


def test_delete_workout_removes_its_exercises(client):
    register_and_login(client)
    workout_id = create_workout(client)
    add_exercise(client, workout_id)
    client.post(f"/workouts/{workout_id}/delete")
    assert client.get(f"/workouts/{workout_id}").status_code == 404
    with app.app_context():
        from app import get_db
        assert get_db().execute("SELECT COUNT(*) FROM exercises").fetchone()[0] == 0


def test_delete_requires_post(client):
    register_and_login(client)
    workout_id = create_workout(client)
    assert client.get(f"/workouts/{workout_id}/delete").status_code == 405


def test_edit_exercise(client):
    register_and_login(client)
    workout_id = create_workout(client)
    add_exercise(client, workout_id)
    exercise_id = first_exercise_id(workout_id)
    client.post(
        f"/exercises/{exercise_id}/edit",
        data={"name": "Incline press", "sets": "4", "reps": "6", "weight": "50"},
    )
    page = client.get(f"/workouts/{workout_id}").data
    assert b">Incline press<" in page and b">Bench press<" not in page


def test_edit_exercise_validation_keeps_input(client):
    register_and_login(client)
    workout_id = create_workout(client)
    add_exercise(client, workout_id)
    exercise_id = first_exercise_id(workout_id)
    response = client.post(
        f"/exercises/{exercise_id}/edit",
        data={"name": "Typo name", "sets": "0", "reps": "6", "weight": ""},
    )
    assert b"Sets and reps must be at least 1." in response.data
    assert b'value="Typo name"' in response.data


def test_delete_exercise(client):
    register_and_login(client)
    workout_id = create_workout(client)
    add_exercise(client, workout_id)
    client.post(f"/exercises/{first_exercise_id(workout_id)}/delete")
    assert b"No exercises logged yet." in client.get(f"/workouts/{workout_id}").data


# ---------- Privacy: users can't touch each other's data ----------

def test_other_user_cannot_view_edit_or_delete_workout(client, other_client):
    register_and_login(client)
    workout_id = create_workout(client)
    assert other_client.get(f"/workouts/{workout_id}").status_code == 404
    assert other_client.post(
        f"/workouts/{workout_id}/edit", data={"name": "Hacked", "date": "2026-11-03"}
    ).status_code == 404
    assert other_client.post(f"/workouts/{workout_id}/delete").status_code == 404
    assert b"Push day" in client.get(f"/workouts/{workout_id}").data  # unchanged


def test_other_user_cannot_edit_or_delete_exercise(client, other_client):
    register_and_login(client)
    workout_id = create_workout(client)
    add_exercise(client, workout_id)
    exercise_id = first_exercise_id(workout_id)
    assert other_client.get(f"/exercises/{exercise_id}/edit").status_code == 404
    assert other_client.post(f"/exercises/{exercise_id}/delete").status_code == 404
    assert b"Bench press" in client.get(f"/workouts/{workout_id}").data  # still there


def test_other_user_cannot_add_exercise(client, other_client):
    register_and_login(client)
    workout_id = create_workout(client)
    response = other_client.post(
        f"/workouts/{workout_id}/exercises", data={"name": "X", "sets": "1", "reps": "1"}
    )
    assert response.status_code == 404


# ---------- Sprint 3: exercise history ----------

def test_history_shows_all_entries_and_personal_record(client):
    register_and_login(client)
    week1 = create_workout(client, date="2026-10-20")
    week2 = create_workout(client, date="2026-10-27")
    add_exercise(client, week1, weight="60")
    add_exercise(client, week2, name="bench PRESS", weight="70")  # different case
    page = client.get("/history?exercise=Bench press").data
    assert b"2026-10-20" in page and b"2026-10-27" in page
    assert b"<strong>70 kg</strong>" in page


def test_history_only_shows_own_entries(client, other_client):
    register_and_login(client)
    add_exercise(client, create_workout(client), weight="100")
    page = other_client.get("/history?exercise=Bench press").data
    assert b"haven't logged" in page
    assert b"100" not in page


def test_history_with_no_weights_has_no_record(client):
    register_and_login(client)
    add_exercise(client, create_workout(client), name="Pull-up", weight="")
    assert b"Personal record" not in client.get("/history?exercise=Pull-up").data


def test_dashboard_lists_exercise_history_links(client):
    register_and_login(client)
    workout_id = create_workout(client)
    add_exercise(client, workout_id)
    add_exercise(client, workout_id, name="bench press")
    assert b"logged 2 times" in client.get("/").data


# ---------- Weight formatting ----------

@pytest.mark.parametrize("value, expected", [
    (60.0, "60"), (22.5, "22.5"), (0.0, "0"), (None, ""), ("", ""), ("abc", "abc"),
])
def test_format_weight(value, expected):
    assert format_weight(value) == expected
