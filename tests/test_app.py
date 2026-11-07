import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/t.db"
os.environ["UPLOAD_DIR"] = f"{_tmp}/up"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app, hash_pw  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Recruiter, Job  # noqa: E402

client = TestClient(app)


def setup_module():
    db = SessionLocal()
    db.add(Recruiter(email="r@x.com", password_hash=hash_pw("pw")))
    db.add(Job(title="Dev", required_skills=["python"], min_years=1))
    db.commit()
    db.close()


def test_recruiter_pages_require_login():
    r = client.get("/recruiter", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/recruiter/login"


def test_apply_requires_consent():
    r = client.post("/jobs/1/apply", data={"name": "A", "email": "a@x.com"},
                    files={"resume": ("r.txt", b"python")}, follow_redirects=False)
    assert r.status_code == 400


def test_rejects_bad_file_type():
    r = client.post("/jobs/1/apply", data={"name": "A", "email": "a@x.com", "consent": "on"},
                    files={"resume": ("r.exe", b"x")}, follow_redirects=False)
    assert r.status_code == 400


def test_full_flow():
    r = client.post("/jobs/1/apply", data={"name": "Ann Lee", "email": "ann@x.com", "consent": "on"},
                    files={"resume": ("r.txt", b"Ann Lee\nPython dev 2019 - Present")}, follow_redirects=False)
    assert r.status_code == 303
    dup = client.post("/jobs/1/apply", data={"name": "Ann Lee", "email": "ann@x.com", "consent": "on"},
                      files={"resume": ("r.txt", b"x")}, follow_redirects=False)
    assert "done=dup" in dup.headers["location"]

    assert client.post("/recruiter/login", data={"email": "r@x.com", "password": "pw"},
                       follow_redirects=False).status_code == 303
    page = client.get("/recruiter/jobs/1")
    assert "Ann Lee" in page.text
    d = client.post("/recruiter/applications/1/decide", data={"status": "shortlisted"}, follow_redirects=False)
    assert d.status_code == 303
    assert "shortlisted" in client.get("/recruiter/applications/1").text
    assert "decision:shortlisted" in client.get("/recruiter/audit").text
    assert client.post("/recruiter/candidates/1/delete", follow_redirects=False).status_code == 303
    assert "Ann Lee" not in client.get("/recruiter/jobs/1").text


def test_bad_login():
    assert client.post("/recruiter/login", data={"email": "r@x.com", "password": "nope"}).status_code == 401


def test_knockout_routes_to_review_not_reject():
    from app.scoring import decide
    from app.models import Job
    job = Job(title="Dev", shortlist_threshold=70, reject_threshold=35)
    # A missing must-have keyword must never bury a strong candidate as "reject".
    assert decide(100.0, True, job) == "review"
    assert decide(10.0, True, job) == "review"
    # Without a knockout, score-based decision is unchanged.
    assert decide(80.0, False, job) == "shortlist"
    assert decide(20.0, False, job) == "reject"
    assert decide(50.0, False, job) == "review"
