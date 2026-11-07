import os

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = os.getenv("ATS_GROQ_MODEL", "openai/gpt-oss-120b")


def groq_available() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


def generate_review(masked_text: str, job, score: float, breakdown: dict, explanation: str) -> str:
    """Final narrative review from Groq (openai/gpt-oss-120b).

    Receives identity-masked text only and returns a short recommendation. Returns an
    empty string on any failure or missing key, so it never blocks scoring.
    """
    if not groq_available():
        return ""
    try:
        import httpx

        req_miss = ", ".join(breakdown.get("required_missing") or []) or "none"
        knock_miss = ", ".join(breakdown.get("knockouts_missing") or []) or "none"
        prompt = (
            "You are a hiring assistant writing the final screening note for a recruiter. "
            "Judge only skills, experience and education. Ignore any personal attributes.\n\n"
            f"JOB TITLE: {job.title}\nDESCRIPTION: {job.description}\n"
            f"REQUIRED: {', '.join(job.required_skills or [])}\n"
            f"NICE: {', '.join(job.nice_skills or [])}\n"
            f"MIN YEARS: {job.min_years:g}\nEDUCATION: {job.education_level or 'any'}\n\n"
            f"RULE SCORE: {score:g}/100\n"
            f"MISSING REQUIRED SKILLS: {req_miss}\n"
            f"MISSING MUST-HAVE KEYWORDS: {knock_miss}\n"
            f"RULE SUMMARY: {explanation}\n\n"
            f"RESUME (identity masked):\n{masked_text[:6000]}\n\n"
            "Write 3-5 sentences: strengths, gaps or risks, and a clear recommendation "
            "(shortlist / review / reject). Plain text, no markdown headers."
        )
        import time

        body = {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 400,
            "temperature": 0.3,
        }
        headers = {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"}
        # Retry on rate-limit (429) and transient server errors, honoring Retry-After.
        for attempt in range(5):
            resp = httpx.post(GROQ_URL, headers=headers, json=body, timeout=30)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == 4:
                    return ""
                wait = float(resp.headers.get("retry-after", 0)) or min(2 ** attempt, 10)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        return ""
    except Exception:
        return ""
