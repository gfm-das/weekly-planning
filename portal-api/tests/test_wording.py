"""Unit checks for the round-3 wording pass (no database needed).

- The key indicator "Friends Found" is shown as "New People Being Taught" (Preach My Gospel's name) everywhere this
  stream owns, while every hidden name stays (friends_found, friends_found_actual/goal/plan).
- The Overview's English label is the catalog's English text, so the interface translation finds it, and each
  language uses its Preach My Gospel wording.
- Every text of the calendar and announcement confirmations and of the reminders switch is in the catalog.
- German reminder notices say "Benachrichtigungen" (browser notifications), not "Mitteilungen" (Announcements).
- Weekly Planning's create-form messages are the server's, word for word, including "Please choose one." and
  "Please fill this in."; no old words ("Save failed", "reporting unit", "from the database") are left; "Add from
  list" says whether everyone is already on the plan or no one is listed yet.
- The database's old "Use Drop instead." becomes the page's "No longer on date".
- On the Call-ins district page a locked area card points to the Reopen call-in button, not to "the district page".
- The Overview's rotating thoughts in our own words are labelled "Mission thought", never Preach My Gospel.

Run in the portal-api image with the portal folder mounted at /portal (the page checks need it):
  docker run --rm -v <repo>/portal-api:/app -v <repo>/portal:/portal:ro -w /app gfm-portal-portal-api python tests/test_wording.py
"""
import ast
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SUPABASE_URL", "http://supabase.invalid")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "unit-test-only")
import app  # noqa: E402
import callins  # noqa: E402
import planning  # noqa: E402

PORTAL = next((path for path in (Path(__file__).resolve().parents[2] / "portal", Path("/portal"))
               if (path / "planning.html").exists()), None)
NEW_NAME = "New people being taught"
# Preach My Gospel (2023), chapter 8, "Key Indicators for Conversion", in each language's edition (Persian has no
# chapter 8 yet: the mission's own wording, see docs/handoff/round6/i18n.md).
PMG_NAMES = {"en": NEW_NAME, "de": "Neue Personen, die unterwiesen werden",
             "es": "Personas nuevas a las que se está enseñando", "fr": "Nouvelles personnes instruites actuellement",
             "pt": "Novas pessoas sendo ensinadas", "uk": "Нові люди, яких навчають",
             "ru": "Новые люди, проходящие обучение", "it": "Nuove persone a cui si sta insegnando",
             "tr": "Yeni insanlar öğretiliyor", "fa": "افراد تازه‌ای که آموزش می‌بینند",
             "ro": "Oameni noi cărora li se propovăduiește", "sv": "Nya personer som undervisas",
             "da": "Nye personer, der undervises", "ar": "أشخاص جدد يتم تعليمهم"}
# Round 6: one catalog per language (portal/i18n/<code>.json); catalogs.json lists the languages.
CATALOG_FILES = ["i18n/catalogs.json", "i18n/en.json"]


def page(name):
    return (PORTAL / name).read_text(encoding="utf-8")


def catalog():
    """{"messages": {language: {key: text}}} from the per-language catalogs."""
    languages = json.loads(page("i18n/catalogs.json"))["languages"]
    return {"messages": {code: json.loads(page(f"i18n/{code}.json")) for code in languages}}


def english_values():
    return {text for value in catalog()["messages"]["en"].values()
            for text in (value.values() if isinstance(value, dict) else [value])}


def skipped():
    if PORTAL is None:
        print("   (skipped: the portal folder is not mounted)")
        return True
    return False


# ---------- the key indicator's name ----------

def test_the_api_shows_the_new_name_and_keeps_the_hidden_names():
    indicator = next(row for row in planning.KEY_INDICATORS if row[0] == "friends_found")
    assert indicator == ("friends_found", NEW_NAME, "friends_found_actual", "friends_found_goal",
                         "friends_found_actual", "friends_found_goal", "friends_found_plan"), indicator
    assert dict(callins.METRICS)["friends_found"] == NEW_NAME
    assert callins.PLAN_KEYS[0] == "friends_found"
    assert app.KPI_KEYS[0] == "friends_found"


def test_no_page_or_api_text_of_this_stream_says_friends_found():
    sources = [Path(planning.__file__), Path(callins.__file__), Path(app.__file__)]
    if PORTAL is not None:
        sources += [PORTAL / name for name in ("planning.html", "callins.html", "home.html", "calendar.html",
                                               "announcements.html", "portal-enhancements.js", *CATALOG_FILES)]
    for source in sources:
        text = source.read_text(encoding="utf-8")
        if source.name == "en.json":
            # question.* mirror the planning questions' own labels in the database ("Friends Found through Facebook"
            # is a finding question, not the key indicator), so they may say what the database says.
            text = json.dumps({k: v for k, v in json.loads(text).items() if not k.startswith("question.")})
        # Only hidden names may remain (friends_found, friends_found_actual, ...).
        assert not re.search(r"friends[ -]found", text, re.I), source.name


def test_the_overview_label_is_the_catalog_text_in_every_language():
    if skipped():
        return
    messages = catalog()["messages"]
    assert {locale: messages[locale]["indicator.friends"] for locale in messages} == PMG_NAMES
    labels = json.loads("[" + re.search(r"const indicatorLabels = \[(.*?)\];", page("home.html"), re.S).group(1)
                        .strip().rstrip(",") + "]")
    assert labels == [row[1] for row in planning.KEY_INDICATORS], labels
    # The interface translation replaces a label only when it is exactly an English catalog text.
    assert set(labels) <= english_values(), set(labels) - english_values()


def test_the_call_ins_page_uses_the_new_name():
    if skipped():
        return
    script = page("callins.html")
    for name in ("SHORT", "PLAN_LABELS"):
        block = re.search(rf"const {name} = \{{(.*?)\}};", script, re.S).group(1)
        assert f'friends_found: "{NEW_NAME}",' in block, name


# ---------- confirmations and reminders translate ----------

def confirm_texts(html):
    """The English texts of every portalConfirm({...}) on a page (title, message, choice labels, keep)."""
    texts = []
    for call in re.findall(r"portalConfirm\((.*?)\);", html, re.S):
        for key, literal in re.findall(r"\b(title|message|label|keep):\s*(\"(?:[^\"\\]|\\.)*\")", call):
            texts.append(ast.literal_eval(literal))
    return texts


def test_every_confirmation_text_is_in_the_catalog():
    if skipped():
        return
    english = english_values()
    for name in ("calendar.html", "announcements.html"):
        texts = confirm_texts(page(name))
        assert len(texts) >= 8 if name == "calendar.html" else len(texts) >= 6, (name, texts)
        assert "Keep" in texts, name
        missing = [text for text in texts if text not in english]
        assert not missing, (name, missing)
    assert "Only this one" in confirm_texts(page("calendar.html"))


def test_the_reminder_notices_are_in_the_catalog():
    if skipped():
        return
    script = page("portal-enhancements.js")
    english = english_values()
    for key in ("reminders.on", "reminders.off", "reminders.blocked", "reminders.unsupported", "reminders.offFailed",
                "reminders.turnOff"):
        text = catalog()["messages"]["en"][key]
        assert f"'{text}'" in script, key
    notices = re.findall(r"'((?:Reminders|Notifications|This browser)[^']*)'", script)
    assert notices and all(text in english for text in notices), [text for text in notices if text not in english]


def test_german_reminders_do_not_use_the_announcements_word():
    """German "Mitteilungen" is the portal's name for Announcements; browser notifications are "Benachrichtigungen",
    as in German Chrome and Edge settings."""
    if skipped():
        return
    german = catalog()["messages"]["de"]
    assert german["announcements.title"] == "Mitteilungen"
    assert german["reminders.blocked"].startswith("Benachrichtigungen sind für diese Seite blockiert."), \
        german["reminders.blocked"]
    for key, text in german.items():
        if key.startswith("reminders."):
            assert "Mitteilung" not in text, key


def test_the_overview_status_words_translate():
    if skipped():
        return
    html, english = page("home.html"), english_values()
    for text in ("Not submitted yet", "This area’s plan is not submitted yet", "Mission thought"):
        assert text in english, text
    assert html.count('"Not submitted yet"') == 1 and ">\n            Not submitted yet</button" in html.replace("\r\n", "\n")
    assert '"This area’s plan is not submitted yet"' in html


# ---------- Weekly Planning ----------

def js_object(html, name):
    block = re.search(rf"const {name} = \{{(.*?)\}};", html, re.S).group(1)
    return {key: ast.literal_eval(literal) for key, literal in
            re.findall(r"(\w+):\s*(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')", block)}


def test_the_create_form_messages_are_the_servers():
    if skipped():
        return
    html = page("planning.html")
    assert js_object(html, "CREATE_REQUIRED_TEXT") == planning.REQUIRED_MESSAGES
    assert js_object(html, "CREATE_DATE_LABELS") == planning.DATE_LABELS


def test_the_create_form_fallback_messages_are_the_guides_and_the_servers():
    """A choice or text without its own message says "Please choose one." / "Please fill this in.", on the page and
    in planning.validate_new_person, word for word."""
    if skipped():
        return
    choose, fill = re.search(r'type === "select" \? "([^"]+)" : "([^"]+)"', page("planning.html")).groups()
    assert (choose, fill) == ("Please choose one.", "Please fill this in."), (choose, fill)
    try:
        planning.validate_new_person("baptismal", {"first_name": "Mia", "last_name": "Klein"})
        raise AssertionError("a missing finding source was accepted")
    except planning.FieldErrors as error:
        assert error.fields == {"finding_source": choose}, error.fields
    assert f'missing(key, "{fill}")' in Path(planning.__file__).read_text(encoding="utf-8")


def test_no_old_words_are_left_in_weekly_planning():
    """The guide's words: ward or branch (not unit), your list (not the database), never "failed"."""
    if skipped():
        return
    html, server = page("planning.html"), Path(planning.__file__).read_text(encoding="utf-8")
    for old in ("Save failed", "reporting unit was not changed", "Choose an option.", "This field is required.",
                "mission database", "There are no additional current records"):
        assert old not in html, old
    for old in ("Choose a person from the database.", "Choose an option.", "This field is required."):
        assert old not in server, old
    assert '"Not saved"' in html and "Your ward or branch was not changed." in html
    assert '"Choose a person from your list."' in server


def test_add_from_list_says_why_it_is_empty():
    """Nobody left to add because everyone is on the plan, or because nobody is listed yet: two different texts
    (tests/edge_planning_wording.ps1 checks both in the browser)."""
    if skipped():
        return
    picker = re.search(r"function openPersonPicker\(kind\) \{(.*?)\n      \}", page("planning.html"), re.S).group(1)
    for text in ("Everyone on your area's list is already on this week's plan.",
                 "No new members are listed for your area in this ward or branch yet.",
                 "No friends with a baptismal date are listed for your area yet.",
                 "No one else to add", "No one to add yet"):
        assert text in picker, text
    assert "data.people?.[kind]" in picker


def test_the_user_words_stay_on_the_person_buttons():
    """"Transfer", "Delete" and "Baptized" are the user's words; "Drop" became "No longer on date"."""
    if skipped():
        return
    html = page("planning.html")
    actions = re.search(r"function personActions\(p, group\) \{(.*?)\n      \}", html, re.S).group(1)
    for button in ('["transfer", "Transfer"]', '["delete", "Delete"]', '["baptized", "Baptized"]',
                   '["drop", "No longer on date"]', '["end", "End follow-up"]', '["edit", "Edit details"]'):
        assert button in actions, button
    assert '"Drop"' not in html and "Drop instead" not in html


def test_the_old_drop_button_in_database_messages_becomes_the_new_one():
    error = SimpleNamespace(pgcode="GF409", diag=SimpleNamespace(message_primary=(
        "This friend is already on an earlier or submitted weekly plan, so the record is kept for the mission's "
        "reports. Use Drop instead.")))
    mapped = planning._person_rpc_error(error, "Mia Klein")
    assert isinstance(mapped, planning.PersonActionRefused)
    assert str(mapped) == ("Mia Klein is already on an earlier or submitted weekly plan, so the record is kept for the "
                           "mission's reports. Use \"No longer on date\" instead."), str(mapped)


# ---------- Call-ins: the locked area card on the district page ----------

def test_the_district_page_points_to_the_reopen_button():
    if skipped():
        return
    script = page("callins.html")
    locked = re.search(r"locked:\s*(s\.dl_call_in_complete.*?)\n\s*empty:", script, re.S).group(1)
    district, area = re.findall(r'"(The district call-in is complete[^"]*)"', locked)
    assert 'd.scope.level === "district"' in locked
    assert "Reopen call-in" in district and "district page" not in district, district
    assert "district page" in area, area


# ---------- Overview: thoughts in our own words ----------

def test_mission_thoughts_are_not_attributed_to_preach_my_gospel():
    real = datetime
    seen = {}
    for day in range(12):
        fake = SimpleNamespace(now=lambda tz=None, day=day: real.now(tz) + timedelta(days=day))
        with patch.object(app, "datetime", fake):
            choice = app.inspiration()
        seen[choice["text"]] = choice
    thoughts = [choice for choice in seen.values() if choice.get("source") == "Mission thought"]
    assert len(thoughts) == 3, list(seen)
    for thought in thoughts:
        assert not {"paraphrase", "reference", "url"} & set(thought), thought
    assert any(choice.get("paraphrase") for choice in seen.values())  # the Preach My Gospel paraphrase stays labelled


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print("ok", test.__name__)
        except Exception as exc:  # keep going so a run shows every failing check
            failed += 1
            print("FAIL", test.__name__, "-", type(exc).__name__, str(exc)[:400])
    print(f"{len(tests) - failed} of {len(tests)} tests passed")
    sys.exit(1 if failed else 0)
