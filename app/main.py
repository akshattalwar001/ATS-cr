import hashlib
import hmac
import os
import secrets
import uuid
from pathlib import Path

from fastapi import FastAPI, Depends, Request, Form, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import brand
from .db import Base, engine, get_db
from .models import Recruiter, Job, Candidate, Application, AuditLog
from .pipeline import process_application
from .llm import llm_available

BASE = Path(__file__).parent
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(exist_ok=True)
ALLOWED_EXT = {".pdf", ".docx", ".txt"}
MAX_BYTES = 5 * 1024 * 1024

app = FastAPI(title="ATS")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "dev-only-change-me"))
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
SVG_HEADERS = {"Cache-Control": "public, max-age=3600"}


@app.get("/brand/logo.svg", include_in_schema=False)
def brand_logo():
    return Response(brand.wordmark(), media_type="image/svg+xml", headers=SVG_HEADERS)


@app.get("/brand/mark.svg", include_in_schema=False)
def brand_mark():
    return Response(brand.mark(), media_type="image/svg+xml", headers=SVG_HEADERS)


@app.get("/brand/favicon.svg", include_in_schema=False)
def brand_favicon():
    return Response(brand.favicon(False), media_type="image/svg+xml", headers=SVG_HEADERS)


@app.get("/brand/favicon-recruiter.svg", include_in_schema=False)
def brand_favicon_recruiter():
    return Response(brand.favicon(True), media_type="image/svg+xml", headers=SVG_HEADERS)


templates = Jinja2Templates(directory=str(BASE / "templates"))
templates.env.globals["company"] = os.getenv("COMPANY_NAME", "Cloud Reboot")
Base.metadata.create_all(engine)


def _bootstrap_recruiter():
    email, pw = os.getenv("ADMIN_EMAIL", "").strip().lower(), os.getenv("ADMIN_PASSWORD", "")
    if not email or len(pw) < 8:
        return
    from .db import SessionLocal
    with SessionLocal() as db:
        if not db.scalar(select(Recruiter).where(Recruiter.email == email)):
            db.add(Recruiter(email=email, password_hash=hash_pw(pw)))
            db.commit()


def hash_pw(pw: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return salt.hex() + "$" + h.hex()


def check_pw(pw: str, stored: str) -> bool:
    salt_hex, h = stored.split("$")
    return hmac.compare_digest(hash_pw(pw, bytes.fromhex(salt_hex)).split("$")[1], h)


_bootstrap_recruiter()


class NeedLogin(Exception):
    pass


@app.exception_handler(NeedLogin)
def _need_login(request, exc):
    return RedirectResponse("/recruiter/login", status_code=303)


def current_user(request: Request) -> str:
    u = request.session.get("user")
    if not u:
        raise NeedLogin()
    return u


def audit(db, actor, action, app_id=None, detail=""):
    db.add(AuditLog(actor=actor, action=action, application_id=app_id, detail=detail))


def csv_list(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


# ---------- public careers site ----------
@app.get("/", response_class=HTMLResponse)
def careers(request: Request, db: Session = Depends(get_db)):
    jobs = db.scalars(select(Job).where(Job.is_open == True).order_by(Job.id)).all()  # noqa: E712
    return templates.TemplateResponse(request, "careers.html", {"jobs": jobs})


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(job_id: int, request: Request, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job or not job.is_open:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "job.html", {"job": job, "done": request.query_params.get("done")})


@app.post("/jobs/{job_id}/apply")
async def apply(job_id: int, bg: BackgroundTasks, db: Session = Depends(get_db),
                name: str = Form(...), email: str = Form(...), phone: str = Form(""),
                consent: str = Form(None), resume: UploadFile = File(...)):
    job = db.get(Job, job_id)
    if not job or not job.is_open:
        raise HTTPException(404)
    if not consent:
        raise HTTPException(400, "Consent is required to apply.")
    ext = Path(resume.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, "Resume must be PDF, DOCX or TXT.")
    data = await resume.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(400, "Resume too large (max 5 MB).")
    path = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(data)

    cand = db.scalar(select(Candidate).where(Candidate.email == email))
    if not cand:
        cand = Candidate(name=name, email=email, phone=phone, consent=True)
        db.add(cand)
        db.flush()
    dup = db.scalar(select(Application).where(Application.job_id == job.id,
                                              Application.candidate_id == cand.id))
    if dup:
        path.unlink(missing_ok=True)
        return RedirectResponse(f"/jobs/{job.id}?done=dup", status_code=303)
    application = Application(job_id=job.id, candidate_id=cand.id, resume_path=str(path))
    db.add(application)
    db.commit()
    bg.add_task(process_application, application.id)
    return RedirectResponse(f"/jobs/{job.id}?done=1", status_code=303)


# ---------- recruiter auth ----------
@app.get("/recruiter/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/recruiter/login")
def login(request: Request, db: Session = Depends(get_db), email: str = Form(...), password: str = Form(...)):
    r = db.scalar(select(Recruiter).where(Recruiter.email == email))
    if not r or not check_pw(password, r.password_hash):
        return templates.TemplateResponse(request, "login.html", {"error": "Invalid credentials"}, status_code=401)
    request.session["user"] = r.email
    return RedirectResponse("/recruiter", status_code=303)


@app.get("/recruiter/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# ---------- recruiter tool ----------
@app.get("/recruiter", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), user: str = Depends(current_user)):
    jobs = db.scalars(select(Job).order_by(Job.id)).all()
    stats = {}
    for j in jobs:
        apps = j.applications
        stats[j.id] = {
            "total": len(apps),
            "to_review": sum(1 for a in apps if a.auto_status == "review" and not a.decided_by_human),
            "reject_queue": sum(1 for a in apps if a.auto_status == "reject" and not a.decided_by_human),
        }
    return templates.TemplateResponse(request, "dashboard.html",
                                      {"jobs": jobs, "stats": stats, "user": user, "llm_ok": llm_available()})


@app.get("/recruiter/jobs/new", response_class=HTMLResponse)
def job_new(request: Request, user: str = Depends(current_user)):
    return templates.TemplateResponse(request, "job_form.html", {"job": None, "llm_ok": llm_available()})


@app.get("/recruiter/jobs/{job_id}/edit", response_class=HTMLResponse)
def job_edit(job_id: int, request: Request, db: Session = Depends(get_db), user: str = Depends(current_user)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "job_form.html", {"job": job, "llm_ok": llm_available()})


@app.post("/recruiter/jobs/save")
def job_save(db: Session = Depends(get_db), user: str = Depends(current_user),
             job_id: int = Form(0), title: str = Form(...), description: str = Form(""),
             location: str = Form(""), required_skills: str = Form(""), nice_skills: str = Form(""),
             min_years: float = Form(0), education_level: str = Form(""), knockouts: str = Form(""),
             shortlist_threshold: float = Form(70), reject_threshold: float = Form(35),
             use_llm: str = Form(None), is_open: str = Form(None)):
    job = db.get(Job, job_id) if job_id else Job()
    job.title, job.description, job.location = title, description, location
    job.required_skills, job.nice_skills = csv_list(required_skills), csv_list(nice_skills)
    job.min_years, job.education_level = min_years, education_level
    job.knockouts = csv_list(knockouts)
    job.shortlist_threshold, job.reject_threshold = shortlist_threshold, reject_threshold
    job.use_llm, job.is_open = bool(use_llm), bool(is_open)
    db.add(job)
    audit(db, user, "job_saved", detail=title)
    db.commit()
    return RedirectResponse(f"/recruiter/jobs/{job.id}", status_code=303)


@app.get("/recruiter/jobs/{job_id}", response_class=HTMLResponse)
def job_candidates(job_id: int, request: Request, view: str = "all",
                   db: Session = Depends(get_db), user: str = Depends(current_user)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    apps = sorted(job.applications, key=lambda a: (a.score is None, -(a.score or 0)))
    human = lambda a: not a.decided_by_human  # noqa: E731
    counts = {
        "all": len(apps),
        "review": sum(1 for a in apps if a.auto_status == "review" and human(a)),
        "reject_queue": sum(1 for a in apps if a.auto_status == "reject" and human(a)),
        "shortlisted": sum(1 for a in apps if a.status == "shortlisted"),
        "hold": sum(1 for a in apps if a.status == "hold"),
        "rejected": sum(1 for a in apps if a.status == "rejected"),
    }
    if view == "reject_queue":
        apps = [a for a in apps if a.auto_status == "reject" and not a.decided_by_human]
    elif view == "review":
        apps = [a for a in apps if a.auto_status == "review" and not a.decided_by_human]
    elif view in ("shortlisted", "hold", "rejected"):
        apps = [a for a in apps if a.status == view]
    return templates.TemplateResponse(request, "candidates.html", {"job": job, "apps": apps, "view": view, "counts": counts})


@app.post("/recruiter/jobs/{job_id}/rescore")
def rescore(job_id: int, bg: BackgroundTasks, db: Session = Depends(get_db), user: str = Depends(current_user)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    for a in job.applications:
        bg.add_task(process_application, a.id)
    audit(db, user, "rescore_job", detail=job.title)
    db.commit()
    return RedirectResponse(f"/recruiter/jobs/{job_id}", status_code=303)


@app.get("/recruiter/applications/{app_id}", response_class=HTMLResponse)
def application_detail(app_id: int, request: Request, db: Session = Depends(get_db), user: str = Depends(current_user)):
    a = db.get(Application, app_id)
    if not a:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "application.html", {"a": a})


@app.get("/recruiter/applications/{app_id}/resume")
def resume_file(app_id: int, download: int = 0, db: Session = Depends(get_db), user: str = Depends(current_user)):
    a = db.get(Application, app_id)
    if not a or not Path(a.resume_path).is_file():
        raise HTTPException(404, "Resume file not found")
    p = Path(a.resume_path)
    types = {".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8",
             ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    safe = "".join(c for c in a.candidate.name if c.isalnum() or c in " -_").strip() or "resume"
    disp = "attachment" if download or p.suffix.lower() == ".docx" else "inline"
    audit(db, user, "resume_viewed", a.id)
    db.commit()
    return FileResponse(p, media_type=types.get(p.suffix.lower(), "application/octet-stream"),
                        filename=f"{safe} resume{p.suffix.lower()}", content_disposition_type=disp)


@app.post("/recruiter/applications/{app_id}/decide")
def decide_application(app_id: int, db: Session = Depends(get_db), user: str = Depends(current_user),
                       status: str = Form(...), notes: str = Form("")):
    if status not in ("shortlisted", "hold", "rejected", "new"):
        raise HTTPException(400)
    a = db.get(Application, app_id)
    if not a:
        raise HTTPException(404)
    a.status, a.decided_by_human = status, True
    if notes:
        a.notes = notes
    audit(db, user, f"decision:{status}", a.id, f"auto={a.auto_status} score={a.score}")
    db.commit()
    return RedirectResponse(f"/recruiter/jobs/{a.job_id}", status_code=303)


@app.post("/recruiter/candidates/{cand_id}/delete")
def delete_candidate(cand_id: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    c = db.get(Candidate, cand_id)
    if not c:
        raise HTTPException(404)
    for a in c.applications:
        Path(a.resume_path).unlink(missing_ok=True)
    audit(db, user, "candidate_deleted", detail=f"id={cand_id}")
    db.delete(c)
    db.commit()
    return RedirectResponse("/recruiter", status_code=303)


@app.get("/recruiter/audit", response_class=HTMLResponse)
def audit_view(request: Request, db: Session = Depends(get_db), user: str = Depends(current_user)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(300)).all()
    return templates.TemplateResponse(request, "audit.html", {"rows": rows})
