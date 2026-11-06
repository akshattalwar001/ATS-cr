from .db import SessionLocal
from .models import Application, AuditLog
from .parser import extract_text, mask_identity
from .scoring import rule_score, decide
from .llm import llm_score


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

        app.parsed = res["parsed"]
        app.breakdown = breakdown
        app.score = score
        app.explanation = explanation
        app.knocked_out = res["knocked_out"]
        app.auto_status = decide(score, res["knocked_out"], job)
        db.add(AuditLog(actor="system", action="scored", application_id=app.id,
                        detail=f"score={score} auto={app.auto_status}"))
        db.commit()
    finally:
        db.close()
