import re
from pathlib import Path

SKILL_ALIASES = {
    "javascript": ["javascript", "js", "ecmascript"],
    "typescript": ["typescript", "ts"],
    "python": ["python"],
    "java": ["java"],
    "c#": ["c#", "csharp", ".net", "dotnet"],
    "sql": ["sql", "postgresql", "postgres", "mysql", "sqlite"],
    "react": ["react", "reactjs", "react.js"],
    "node": ["node", "nodejs", "node.js"],
    "aws": ["aws", "amazon web services"],
    "docker": ["docker", "containers"],
    "kubernetes": ["kubernetes", "k8s"],
    "git": ["git", "github", "gitlab"],
    "excel": ["excel", "spreadsheets"],
    "communication": ["communication", "stakeholder"],
    "sales": ["sales", "business development"],
    "recruiting": ["recruiting", "recruitment", "talent acquisition", "sourcing"],
    "accounting": ["accounting", "bookkeeping", "gaap"],
    "marketing": ["marketing", "seo", "campaigns"],
    "figma": ["figma"],
    "ux": ["ux", "user experience", "usability"],
    "machine learning": ["machine learning", "ml", "deep learning"],
}

EDU_RANK = {"": 0, "highschool": 1, "bachelor": 2, "master": 3, "phd": 4}
EDU_PATTERNS = [
    ("phd", r"\b(ph\.?d|doctorate|doctoral)\b"),
    ("master", r"\b(master'?s?|m\.?sc|m\.?s\.?|mba|m\.?tech)\b"),
    ("bachelor", r"\b(bachelor'?s?|b\.?sc|b\.?s\.?|b\.?a\.?|b\.?e\.?|b\.?tech|undergraduate degree)\b"),
]

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{8,}\d)")
YEARS_RE = re.compile(r"(\d{1,2})(?:\.\d)?\s*\+?\s*(?:years|yrs)", re.I)
RANGE_RE = re.compile(r"((?:19|20)\d{2})\s*[-–to]+\s*((?:19|20)\d{2}|present|current)", re.I)


def extract_text(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    if ext == ".docx":
        import docx
        d = docx.Document(path)
        return "\n".join(p.text for p in d.paragraphs)
    if ext in (".txt", ".md"):
        return Path(path).read_text(errors="ignore")
    raise ValueError(f"Unsupported resume type: {ext}")


def _skill_in_text(skill: str, text: str) -> bool:
    key = skill.lower().strip()
    names = SKILL_ALIASES.get(key, [key])
    for n in names:
        if re.search(r"(?<![\w+#])" + re.escape(n) + r"(?![\w+#])", text, re.I):
            return True
    return False


def estimate_years(text: str) -> float:
    from datetime import date
    this_year = date.today().year
    spans = []
    for a, b in RANGE_RE.findall(text):
        start = int(a)
        end = this_year if b.lower() in ("present", "current") else int(b)
        if end >= start:
            spans.append((start, end))
    merged = 0
    last_end = None
    for s, e in sorted(spans):
        if last_end is None or s > last_end:
            merged += e - s
            last_end = e
        elif e > last_end:
            merged += e - last_end
            last_end = e
    stated = [int(m) for m in YEARS_RE.findall(text)]
    return float(max([merged] + stated)) if (merged or stated) else 0.0


def detect_education(text: str) -> str:
    best = ""
    for level, pat in EDU_PATTERNS:
        if re.search(pat, text, re.I) and EDU_RANK[level] > EDU_RANK[best]:
            best = level
    return best


def parse_resume(text: str) -> dict:
    email = EMAIL_RE.search(text)
    phone = PHONE_RE.search(text)
    skills = sorted(k for k in SKILL_ALIASES if _skill_in_text(k, text))
    return {
        "email": email.group(0) if email else "",
        "phone": phone.group(0).strip() if phone else "",
        "skills": skills,
        "years_experience": estimate_years(text),
        "education": detect_education(text),
        "word_count": len(text.split()),
    }


def mask_identity(text: str, name: str = "", email: str = "", phone: str = "") -> str:
    """Remove identity fields before scoring so they can't influence the result."""
    out = text
    for token in filter(None, [name, email, phone]):
        out = out.replace(token, "[REDACTED]")
    for part in (name or "").split():
        if len(part) > 2:
            out = re.sub(re.escape(part), "[REDACTED]", out, flags=re.I)
    out = EMAIL_RE.sub("[REDACTED]", out)
    out = PHONE_RE.sub("[REDACTED]", out)
    out = re.sub(r"(?im)^\s*(gender|sex|age|date of birth|dob|nationality|marital status)\s*:.*$", "", out)
    return out
