"""Seed demo data: recruiter login, 3 jobs, ~45 fake resumes. Usage: python seed.py"""
import random
import shutil
from pathlib import Path

from app.db import Base, engine, SessionLocal
from app.models import Recruiter, Job, Candidate, Application
from app.main import hash_pw, UPLOAD_DIR
from app.pipeline import process_application

random.seed(7)

JOBS = [
    dict(title="Senior Python Developer", location="Remote",
         description="Build and scale backend services and APIs for our hiring platform.",
         required_skills=["python", "sql", "git", "docker"], nice_skills=["aws", "kubernetes", "react"],
         min_years=4, education_level="bachelor", knockouts=["work permit"]),
    dict(title="Technical Recruiter", location="Hybrid",
         description="Own full-cycle recruiting for engineering and product roles.",
         required_skills=["recruiting", "communication", "excel"], nice_skills=["sales", "marketing"],
         min_years=2, education_level="", knockouts=[]),
    dict(title="UX Designer", location="Remote",
         description="Design intuitive product experiences from research to polished UI.",
         required_skills=["figma", "ux", "communication"], nice_skills=["react", "marketing"],
         min_years=3, education_level="bachelor", knockouts=[]),
]

FIRST = ["Aarav", "Maya", "Liam", "Sofia", "Noah", "Priya", "Ethan", "Zara", "Lucas", "Ana", "Omar", "Chen",
         "Ivy", "Raj", "Elena", "Tom", "Nia", "Kofi", "Mei", "Diego"]
LAST = ["Sharma", "Garcia", "Kim", "Okafor", "Smith", "Patel", "Rossi", "Nguyen", "Brown", "Silva"]

POOLS = {
    "Senior Python Developer": (["python", "sql", "git", "docker"], ["aws", "kubernetes", "react", "javascript", "java"]),
    "Technical Recruiter": (["recruiting", "communication", "excel"], ["sales", "marketing", "accounting"]),
    "UX Designer": (["figma", "ux", "communication"], ["react", "marketing", "javascript"]),
}
EDU = ["", "B.Sc. in Computer Science", "Bachelor of Arts", "M.Sc. in Engineering", "MBA", "PhD in Informatics"]


def resume_text(name, email, phone, core, extra, years, edu, permit):
    end = 2025
    start = end - years
    skills = ", ".join(core + extra)
    lines = [name, f"{email} | {phone}", "",
             "SUMMARY", f"Professional with experience in {skills}.", "",
             "EXPERIENCE", f"Company A, {start} - {start + years // 2 if years else end}",
             f"Company B, {start + years // 2 if years else end} - Present" if years else "", "",
             "EDUCATION", edu or "Self-taught", "", "SKILLS", skills]
    if permit:
        lines += ["", "Authorization: I hold a valid work permit."]
    lines += ["", "Gender: Female", "Age: 29"] if random.random() < 0.3 else []
    return "\n".join(l for l in lines if l is not None)


def write_file(text, kind, stem):
    path = UPLOAD_DIR / f"{stem}.{kind}"
    if kind == "txt":
        path.write_text(text)
    elif kind == "docx":
        import docx
        d = docx.Document()
        for line in text.split("\n"):
            d.add_paragraph(line)
        d.save(path)
    else:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(str(path), pagesize=A4)
        y = 800
        for line in text.split("\n"):
            c.drawString(50, y, line)
            y -= 16
        c.save()
    return path


def main():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    if UPLOAD_DIR.exists():
        shutil.rmtree(UPLOAD_DIR)
    UPLOAD_DIR.mkdir()
    db = SessionLocal()
    db.add(Recruiter(email="recruiter@example.com", password_hash=hash_pw("recruiter123")))
    jobs = [Job(**j) for j in JOBS]
    db.add_all(jobs)
    db.commit()

    ids, n = [], 0
    for job in jobs:
        req, pool = POOLS[job.title]
        for i in range(15):
            n += 1
            quality = random.choice(["strong", "strong", "mid", "mid", "weak"])
            name = f"{random.choice(FIRST)} {random.choice(LAST)}"
            email = f"cand{n}@example.com"
            phone = f"+1 555 01{n:02d} 4{n:03d}"
            if quality == "strong":
                core, years, edu = req, random.randint(job.min_years, 12) or 1, random.choice(EDU[1:])
            elif quality == "mid":
                core, years, edu = req[:-1], random.randint(1, int(job.min_years) + 2), random.choice(EDU)
            else:
                core, years, edu = req[:1] if random.random() < .5 else [], random.randint(0, 2), EDU[0]
            extra = random.sample(pool, random.randint(0, 3))
            permit = random.random() > 0.15
            kind = random.choice(["pdf", "pdf", "docx", "txt"])
            text = resume_text(name, email, phone, list(core), extra, int(years), edu, permit)
            path = write_file(text, kind, f"seed{n}")
            cand = Candidate(name=name, email=email, phone=phone, consent=True)
            db.add(cand)
            db.flush()
            app = Application(job_id=job.id, candidate_id=cand.id, resume_path=str(path))
            db.add(app)
            db.flush()
            ids.append(app.id)
    db.commit()
    db.close()
    for aid in ids:
        process_application(aid)
    print(f"Seeded {len(jobs)} jobs and {len(ids)} applications.")
    print("Recruiter login: recruiter@example.com / recruiter123")


if __name__ == "__main__":
    main()
