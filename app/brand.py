import re
from pathlib import Path

LOGO_FILE = Path(__file__).parent.parent / "cr-final-logo.svg"
NAVY, LIGHT = "#16193A", "#ebe8e2"


def _src() -> str:
    s = LOGO_FILE.read_text(encoding="utf-8")
    return re.sub(r"<\?xml[^>]*\?>|<!--.*?-->", "", s, flags=re.S).strip()


def _dark(s: str) -> str:
    return s.replace(NAVY, LIGHT)


def wordmark() -> str:
    return _dark(_src())


def _mark_group() -> str:
    s = _dark(_src())
    style = re.search(r"<style.*?</style>", s, flags=re.S).group(0)
    group = s[s.rfind("<g>"): s.rfind("</svg>")]
    return style + group


def mark() -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 380 235">'
            + _mark_group() + "</svg>")


def favicon(recruiter: bool = False) -> str:
    dot = '<circle cx="352" cy="48" r="26" fill="#a6b8ff" stroke="#0b0d11" stroke-width="10"/>' if recruiter else ""
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400">'
            '<rect width="400" height="400" rx="92" fill="#0b0d11"/>'
            '<svg x="28" y="94" width="344" height="213" viewBox="0 0 380 235">' + _mark_group() + "</svg>"
            + dot + "</svg>")
