from types import SimpleNamespace

from app.parser import parse_resume, mask_identity, estimate_years
from app.scoring import rule_score, decide


def job(**kw):
    base = dict(required_skills=["python", "sql"], nice_skills=["aws"], min_years=3,
                education_level="bachelor", knockouts=[], shortlist_threshold=70, reject_threshold=35)
    base.update(kw)
    return SimpleNamespace(**base)


STRONG = "Experienced in Python, PostgreSQL and AWS.\nAcme 2018 - Present\nB.Sc. in Computer Science"
WEAK = "Barista. Loves coffee.\nCafe 2024 - 2025"


def test_alias_matching():
    assert "sql" in parse_resume("I know PostgreSQL well")["skills"]
    assert "javascript" in parse_resume("Wrote JS for years")["skills"]


def test_no_false_substring_match():
    assert "java" not in parse_resume("I love javascript")["skills"]


def test_years_from_ranges_and_statement():
    assert estimate_years("Acme 2015 - 2020") == 5
    assert estimate_years("I have 8+ years of experience") == 8


def test_strong_beats_weak():
    assert rule_score(STRONG, job())["score"] > rule_score(WEAK, job())["score"]


def test_strong_is_shortlisted_weak_is_rejected():
    s, w = rule_score(STRONG, job()), rule_score(WEAK, job())
    assert decide(s["score"], s["knocked_out"], job()) == "shortlist"
    assert decide(w["score"], w["knocked_out"], job()) == "reject"


def test_knockout():
    r = rule_score(STRONG, job(knockouts=["work permit"]))
    assert r["knocked_out"]
    # A missing must-have keyword routes to human review, not an automatic reject,
    # so a strong candidate who simply didn't phrase it the expected way isn't buried.
    assert decide(r["score"], True, job()) == "review"


def test_knockout_matches_whole_words_only():
    # Word-boundary matching: a knockout keyword embedded in another word is a miss.
    assert rule_score("Experienced permitting specialist", job(knockouts=["permit"]))["knocked_out"]
    assert not rule_score("Holds a valid work permit.", job(knockouts=["work permit"]))["knocked_out"]


def test_masking_removes_identity():
    text = "Jane Doe\njane@x.com | +1 555 010 1234\nGender: F\nPython"
    m = mask_identity(text, "Jane Doe", "jane@x.com", "+1 555 010 1234")
    assert "Jane" not in m and "jane@x.com" not in m and "Gender" not in m
    assert "Python" in m


def test_identity_does_not_change_score():
    a = rule_score(mask_identity("Alice Smith\nPython SQL 2018 - 2024\nB.Sc.", "Alice Smith"), job())
    b = rule_score(mask_identity("Bob Jones\nPython SQL 2018 - 2024\nB.Sc.", "Bob Jones"), job())
    assert a["score"] == b["score"]
