from .parser import _skill_in_text, parse_resume, EDU_RANK

W_REQUIRED, W_NICE, W_EXP, W_EDU = 55, 15, 20, 10


def rule_score(masked_text: str, job) -> dict:
    """Deterministic, explainable score from 0-100. No external calls."""
    parsed = parse_resume(masked_text)
    req = job.required_skills or []
    nice = job.nice_skills or []

    req_hit = [s for s in req if _skill_in_text(s, masked_text)]
    req_miss = [s for s in req if s not in req_hit]
    nice_hit = [s for s in nice if _skill_in_text(s, masked_text)]

    req_pts = W_REQUIRED * (len(req_hit) / len(req)) if req else W_REQUIRED
    nice_pts = W_NICE * (len(nice_hit) / len(nice)) if nice else W_NICE

    years = parsed["years_experience"]
    exp_pts = W_EXP * min(1.0, years / job.min_years) if job.min_years else W_EXP

    need = EDU_RANK.get(job.education_level or "", 0)
    have = EDU_RANK.get(parsed["education"], 0)
    edu_pts = W_EDU if have >= need else W_EDU * (have / need if need else 1)

    knock_miss = [k for k in (job.knockouts or []) if not _skill_in_text(k, masked_text)]

    score = round(req_pts + nice_pts + exp_pts + edu_pts, 1)
    parts = [
        f"Required skills: {len(req_hit)}/{len(req)} matched"
        + (f" (missing: {', '.join(req_miss)})" if req_miss else ""),
        f"Nice-to-have: {len(nice_hit)}/{len(nice)} matched",
        f"Experience: ~{years:g} yrs vs {job.min_years:g} required",
        f"Education: {parsed['education'] or 'not detected'} vs {job.education_level or 'any'}",
    ]
    if knock_miss:
        parts.append("Knockout not found: " + ", ".join(knock_miss))
    return {
        "score": score,
        "knocked_out": bool(knock_miss),
        "parsed": parsed,
        "breakdown": {
            "required": round(req_pts, 1), "nice": round(nice_pts, 1),
            "experience": round(exp_pts, 1), "education": round(edu_pts, 1),
            "required_missing": req_miss, "knockouts_missing": knock_miss,
        },
        "explanation": "; ".join(parts),
    }


def decide(score: float, knocked_out: bool, job) -> str:
    """Machine suggestion only. Every non-shortlist outcome still needs human confirmation."""
    if knocked_out:
        # A missing must-have keyword is often a false negative (the resume simply
        # doesn't phrase it the expected way), so surface it for a person to confirm
        # rather than silently rejecting an otherwise strong candidate.
        return "review"
    if score >= job.shortlist_threshold:
        return "shortlist"
    if score < job.reject_threshold:
        return "reject"
    return "review"
