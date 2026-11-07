from .db import SessionLocal
from .models import Application, AuditLog
from .parser import extract_text, mask_identity, EMAIL_RE, PHONE_RE
from .scoring import rule_score, decide
from .llm import llm_score
from .review import generate_review

MIN_WORDS = 30  # below this the extraction almost certainly failed; don't auto-reject


def process_application(app_id: int) -> None:
    db = SessionLocal()
    try:
        app = db.get(Application, app_id)
        if app is None:
            return
        job, cand = app.job, app.candidate
        try:
            text = extract_text(app.resume_path)
        except Exception as e:
            app.auto_status = "review"
            app.explanation = f"Could not read resume ({e}). Needs manual review."
            db.commit()
            return
        app.resume_text = text
        masked = mask_identity(text, cand.name, cand.email, cand.phone)
        res = rule_score(masked, job)
        score, explanation = res["score"], res["explanation"]
        breakdown = res["breakdown"]

        if job.use_llm:
            llm = llm_score(masked, job)
            if llm:
                breakdown["rule_score"] = score
                breakdown["llm_score"] = llm["score"]
                score = round((score + llm["score"]) / 2, 1)
                explanation += f"; AI: {llm['reason']}"

        # parse_resume ran on masked text, so contact fields come back blank.
        # Recover them from the original text for the recruiter's reference.
        parsed = res["parsed"]
        email, phone = EMAIL_RE.search(text), PHONE_RE.search(text)
        parsed["email"] = email.group(0) if email else ""
        parsed["phone"] = phone.group(0).strip() if phone else ""

        app.parsed = parsed
        app.breakdown = breakdown
        app.score = score
        app.explanation = explanation
        app.knocked_out = res["knocked_out"]

        if parsed.get("word_count", 0) < MIN_WORDS:
            # Extraction succeeded but produced almost no text: a scanned/empty resume
            # should go to a human, never be auto-rejected on a near-zero score.
            app.auto_status = "review"
            app.explanation = (explanation + " ") if explanation else ""
            app.explanation += "Very little text extracted; needs manual review."
        else:
            app.auto_status = decide(score, res["knocked_out"], job)

        app.ai_review = generate_review(masked, job, score, breakdown, app.explanation)
        db.add(AuditLog(actor="system", action="scored", application_id=app.id,
                        detail=f"score={score} auto={app.auto_status}"))
        db.commit()
    finally:
        db.close()
