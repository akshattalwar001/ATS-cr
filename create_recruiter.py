"""Create or reset a recruiter login. Usage: python create_recruiter.py you@company.com"""
import getpass
import sys

from sqlalchemy import select

from app.db import SessionLocal
from app.main import hash_pw
from app.models import Recruiter

if len(sys.argv) != 2:
    sys.exit("Usage: python create_recruiter.py email")
email = sys.argv[1].strip().lower()
pw = getpass.getpass("Password (min 8 chars): ")
if len(pw) < 8:
    sys.exit("Password too short.")
if pw != getpass.getpass("Repeat password: "):
    sys.exit("Passwords do not match.")

db = SessionLocal()
r = db.scalar(select(Recruiter).where(Recruiter.email == email))
if r:
    r.password_hash = hash_pw(pw)
    print("Password updated for", email)
else:
    db.add(Recruiter(email=email, password_hash=hash_pw(pw)))
    print("Recruiter created:", email)
db.commit()
