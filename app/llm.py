import json
import os

MODEL = os.getenv("ATS_LLM_MODEL", "claude-haiku-4-5-20251001")


def llm_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def llm_score(masked_text: str, job) -> dict | None:
    """Optional second opinion. Receives identity-masked text only. Returns None on any failure."""
    if not llm_available():
        return None
    try:
        import anthropic
        client = anthropic.Anthropic()
        prompt = (
            "You are screening a resume against a job. Judge only skills, experience and "
            "education. Ignore any personal attributes.\n\n"
            f"JOB TITLE: {job.title}\nDESCRIPTION: {job.description}\n"
            f"REQUIRED: {', '.join(job.required_skills or [])}\n"
            f"NICE: {', '.join(job.nice_skills or [])}\n\n"
            f"RESUME (identity masked):\n{masked_text[:6000]}\n\n"
            'Reply with JSON only: {"score": 0-100, "reason": "max 2 sentences"}'
        )
        msg = client.messages.create(model=MODEL, max_tokens=200,
                                     messages=[{"role": "user", "content": prompt}])
        text = msg.content[0].text.strip()
        data = json.loads(text[text.find("{"): text.rfind("}") + 1])
        return {"score": max(0.0, min(100.0, float(data["score"]))), "reason": str(data["reason"])}
    except Exception:
        return None
