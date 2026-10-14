"""The English texts of unlocking a locked Weekly Planning question (planning_questions.py, planning_questions_pages.py).

Every text a person sees about unlocking comes from here, each under a key (unlock.*) in the style of the portal's translation
catalog. {name} marks a value filled in on the page. Translation: DA Management loads the portal's i18n.js, which translates these
English texts on the page from portal/i18n/*.json (14 languages). tests/test_unlock.py checks that every text is in the catalog.
"""
from html import escape

TEXT = {
    "unlock.title": "Unlock this question",
    "unlock.warning": "Reports read this question. Dashboards, Call-ins, Presentations or Archetypal Health may break if you change its type, answer choices or show/hide rules, or if you retire it. Unlock it only when you know why, and lock it again when you are done.",
    "unlock.reasonLabel": "Why are you unlocking it? (kept in the change history)",
    "unlock.typeLabel": "Type the question's key to confirm: {code}",
    "unlock.button": "Unlock question",
    "unlock.done": "Question unlocked. It is in the change history with your reason.",
    "unlock.managersOnly": "Only an AP, the President or a Data Analyst can unlock or lock a question.",
    "unlock.reasonNeeded": "Write why you are unlocking it (at least 5 characters).",
    "unlock.typeKey": "Type the question's key exactly to confirm.",
    "unlock.notLocked": "This question is not locked.",
    "unlock.alreadyLocked": "This question is locked.",
    "unlock.unlockedNote": "Unlocked on purpose. Reports read this question, so the database does not protect it until it is locked again.",
    "unlock.lockAgainButton": "Lock question again",
    "unlock.lockedAgain": "Question locked again.",
    "unlock.notLockable": "Only a question that reports read can be locked.",
    "unlock.homeNote": "A manager can unlock a locked question on its page. Every unlock and lock is in the change history with who did it and why.",
}


def plain(key, **values):
    """The English text of a key with its {values} filled in, as plain text."""
    text = TEXT[key]
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def t(key, **values):
    """The same text made safe to put into a page (the text and every value are HTML-escaped)."""
    text = escape(TEXT[key])
    for name, value in values.items():
        text = text.replace("{" + name + "}", escape(str(value)))
    return text
