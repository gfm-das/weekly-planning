"""Planning questions: the rules behind the Weekly Planning question list (migration 024).

The portal's Weekly Planning page builds its form from the planning_question_* tables: sections, questions, answer
choices, grid rows and show/hide rules. DA Management > Planning questions (planning_questions_pages.py) changes
them, and this file holds its rules: keys, the checks of a typed value, the change history, and plain-words
messages for what the database refuses.

Why the rules are strict: reports read the answers by the question's key, so a key never changes, and a question
that Dashboards, Call-ins, Presentations or Archetypal Health read is "locked" (protected). The database triggers
of migration 024 refuse every change that would break saved plans or reports (renaming a key, deleting a question,
changing the type of an answered question, retiring a locked one, ...), also when someone uses Supabase Studio.
Every change also writes a row to planning_catalog_changes in the same transaction, naming the signed-in person.

A change applies at once to every plan that is still a draft. Submitted plans never change.
"""
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

import psycopg2.extras
from flask import request
from psycopg2 import sql

BASE = "/planning-questions"
TYPES = {"NUMBER": "Number", "TEXT": "Short text", "LONG_TEXT": "Long text", "BOOLEAN": "Yes / No",
         "DATE": "Date", "SELECT": "Drop-down list", "RADIO": "Choose one (buttons)",
         "CHECKBOX": "Choose any (tick boxes)", "GRID": "Grid (rows and choices)"}
CHOICE_TYPES = {"SELECT", "RADIO", "CHECKBOX", "GRID"}
# Questions a show/hide rule can look at.
PARENT_TYPES = {"NUMBER", "BOOLEAN", "SELECT", "RADIO"}
OPERATORS = {"equals": "is", "not_equals": "is not", "greater_than": "is more than",
             "greater_than_or_equal": "is at least", "less_than": "is less than", "less_than_or_equal": "is at most"}
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,62}$")
VALUE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{0,62}$")  # answer choice values and grid row keys
TABLE_NAMES = {"planning_question_sections": "Section", "planning_questions": "Question",
               "planning_question_options": "Answer choice", "planning_question_grid_rows": "Grid row",
               "planning_question_visibility_rules": "Show/hide rule", "weekly_planning_answers": "Saved answer"}
KEY_INDICATOR_KEYS = {
    "nm_sacrament_attendance", "nm_sacrament_attendance_goal", "baptisms_confirmations_actual", "baptisms_confirmations_goal",
    "baptismal_dates_actual", "baptismal_dates_goal", "sacrament_attendance_actual", "sacrament_attendance_goal",
    "members_at_lessons_actual", "members_at_lessons_goal", "friends_found_actual", "friends_found_goal"}
LOCK_RULES = ("You can change its wording, help text, order and number limits. Its key, type and Required setting stay the "
              "same, it stays on the form, and its answer choices, rows and show/hide rules stay exactly as they are, so "
              "nothing can hide it and nothing is saved for it while hidden.")
LOCKED_REQUIRED = "Locked questions that are required stay required."
LOCKED_OPTIONAL = ("Locked questions keep this setting, so this one stays optional: once required, a locked question could "
                   "not be made optional again, and every draft plan that leaves it empty could not be submitted.")
WHOLE_LIMITS = ("With “Whole numbers only”, the lowest and highest numbers must be whole numbers too (for example 1, "
                "not 0.5). Otherwise no whole number would fit.")
# Preach My Gospel wording guide (round 3): the questions serve the people missionaries are helping.
# Since 29 Sep 2026 the portal is the only place missionaries plan (the old "Beta" pages, Appsmith, are gone), so no
# text here names Beta or Appsmith; tests/test_page_words.py checks that.
EXPLAIN = ("Missionaries answer these questions every week in Weekly Planning. Ask only what helps companionships plan "
           "and leaders help. Every question adds time to someone's Sunday.")
TIMING = "Wording changes show at once on plans that are still drafts. Submitted plans never change."
PEOPLE_CARDS = ("The questions about new members, friends with a baptismal date and high-potential friends are fixed in "
                "the portal and cannot be changed here.")
# Shown once at the top of the home page (not next to one question), so it speaks of locked questions in general.
LOCKED_NOTE = ("Locked questions are read by Dashboards, Call-ins, Presentations or Archetypal Health. You can change "
               "their wording, help text, order and number limits. Their key, type, Required setting, answer choices "
               "and show/hide rules stay the same, and they cannot be retired. Nothing is ever deleted: a retired "
               "question or section leaves the form, and saved answers stay.")
# Retiring the key indicator section is refused here in plain words, before the database would refuse it (the
# database's own message, from migration 024, still names the old Beta pages).
KEY_SECTION = "key_indicators_conversion"
KEY_SECTION_STAYS = ("“{title}” stays on the form. It holds the key indicators that Dashboards, Call-ins and "
                     "Presentations read every week.")


def protected_reason(key):
    """Why a locked question is locked: who reads it (shown in the yellow "Locked." box on its page)."""
    if key in KEY_INDICATOR_KEYS:
        return "A key indicator: Dashboards, Call-ins and Presentations read it."
    if key.endswith("_plan") and key not in {"weekly_action_plan", "social_media_plan"}:
        return "The action plan of a key indicator: leaders read it in Call-ins."
    if key in {"weekly_action_plan", "information_up_chain"}:
        return "Call-ins and the Overview show it."
    if key.startswith("ward_coordination"):
        return "Call-ins shows it under GEMIKO (ward mission coordination), with its rows and choices."
    if key.startswith(("member_meals_", "member_visits_")):
        return "Call-ins add these up for the member meals and member visits goals."
    if key == "long_term_service":
        # Only the old call-in pages read it. It stays locked so saved answers keep their meaning.
        return "Saved plans keep their answers under this key, so it stays the same."
    return "Reports read this question by its key."


def make_key(text, taken, pattern=KEY_PATTERN, prefix="q"):
    """A key made from a label: small letters, digits and _, unique among taken."""
    value = str(text or "").lower()
    for letter, spelled in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        value = value.replace(letter, spelled)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")[:55].rstrip("_")
    if pattern is KEY_PATTERN and (not value or not value[0].isalpha()):
        value = f"{prefix}_{value}".rstrip("_")
    while pattern is KEY_PATTERN and len(value) < 3:
        value += "_1"
    value = value or prefix
    # A number that makes the key unique goes before _goal, _plan or _actual, which Call-ins read.
    suffix = next((end for end in ("_goal", "_plan", "_actual") if value.endswith(end) and len(value) > len(end)), "")
    base, number = value[:len(value) - len(suffix)], 2
    while value in taken:
        value = f"{base}_{number}{suffix}"
        number += 1
    return value


# ------------------------------------------------------------------------------------------ typed values

def text_field(name, label, limit, required=False, value=None):
    """A text box of the sent form, with extra spaces removed (help text and descriptions keep their lines). None
    when empty. Raises ValueError when it is needed but empty, or too long."""
    raw = request.form.get(name, "") if value is None else value
    cleaned = " ".join(str(raw).split()) if name not in {"help_text", "description"} else str(raw).strip()
    if required and not cleaned:
        raise ValueError(f"{label} is needed.")
    if len(cleaned) > limit:
        raise ValueError(f"{label} can have at most {limit} characters.")
    return cleaned or None


def number_field(name, label):
    """A number box of the sent form (a comma works as the decimal point), or None when empty."""
    raw = request.form.get(name, "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        number = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"{label} must be a number.") from None
    if not number.is_finite() or abs(number) >= Decimal("1e12"):
        raise ValueError(f"{label} must be a number.")
    return number


def plain(number):
    """A number without needless decimals: 3 (not 3.0), 0.5."""
    if number is None:
        return ""
    number = Decimal(str(number))
    return str(int(number)) if number == number.to_integral_value() else format(number.normalize(), "f")


def finite_number(raw):
    """A typed number (a comma works as the decimal point), or None. NaN and Infinity are not numbers here."""
    try:
        number = Decimal(str(raw).strip().replace(",", "."))
    except InvalidOperation:
        return None
    return number if number.is_finite() and abs(number) < Decimal("1e12") else None


def yes_no(raw):
    """'true' or 'false' for Yes, No, true or false (any capitals); None for anything else."""
    return {"yes": "true", "no": "false", "true": "true", "false": "false"}.get(raw.lower())


def choice_code(raw, choices):
    """The code of the answer choice typed as its code or its label (any capitals), or None. choices: (code, label)."""
    return next((c for c, label in choices if raw in (c, label)), None) or next(
        (c for c, label in choices if raw.lower() == str(label).lower()), None)


def hidden_value(kind, raw, low=None, high=None, integer_only=True, choices=()):
    """The "value saved while hidden" as it is stored, checked the way the portal checks a missionary's answer to
    this question (planning._clean_answer): a value the question itself would refuse is refused here.
    choices: (code, label) of the question's active answer choices."""
    if raw is None:
        return None
    if kind in {"GRID", "CHECKBOX"}:
        raise ValueError("Grids and tick-box questions cannot have a value saved while hidden.")
    if kind == "NUMBER":
        return hidden_number(raw, low, high, integer_only)
    if kind == "BOOLEAN":
        word = yes_no(raw)
        if not word:
            raise ValueError("The value saved while hidden must be Yes or No for a yes/no question.")
        return word
    if kind in {"SELECT", "RADIO"}:
        code = choice_code(raw, choices)
        if not code:
            if not choices:
                raise ValueError("Add the answer choices first: the value saved while hidden must be one of them.")
            raise ValueError("The value saved while hidden must be one of the answer choices: " + ", ".join(label for _, label in choices) + ".")
        return code
    if kind == "DATE":
        try:
            day = date.fromisoformat(raw) if len(raw) == 10 else None
        except ValueError:
            day = None
        if day is None or day.year < 1900:
            raise ValueError("The value saved while hidden must be a date written like 2026-10-04.")
        return day.isoformat()
    return raw


def hidden_number(raw, low, high, integer_only):
    """The value saved while hidden of a number question: a number within the question's limits."""
    number = finite_number(raw)
    if number is None:
        raise ValueError("The value saved while hidden must be a number for a number question.")
    lowest = Decimal(0) if low is None else Decimal(str(low))
    highest = None if high is None else Decimal(str(high))
    if integer_only and number != number.to_integral_value():
        raise ValueError("The value saved while hidden must be a whole number: this question takes whole numbers only.")
    if number < lowest or (highest is not None and number > highest):
        allowed = f"from {plain(lowest)} to {plain(highest)}" if highest is not None else f"{plain(lowest)} or more"
        raise ValueError(f"The value saved while hidden must be {allowed}, like every answer to this question.")
    return plain(number)


def friendly(error):
    """A database refusal in plain words (the 024 triggers already speak plainly)."""
    diag = getattr(error, "diag", None)
    constraint = getattr(diag, "constraint_name", None)
    known = {
        "planning_questions_key_format": "A key starts with a small letter and uses only small letters, digits and _ (3 to 63 characters).",
        "planning_question_sections_key_format": "A key starts with a small letter and uses only small letters, digits and _ (3 to 63 characters).",
        "planning_questions_question_key_key": "Another question already uses this key.",
        "planning_question_sections_section_key_key": "Another section already uses this key.",
        "planning_question_options_question_id_option_value_key": "This question already has a choice with that code.",
        "planning_question_grid_rows_question_id_row_key_key": "This grid already has a row with that code.",
        "planning_visibility_unique": "This question already has a rule for that question. Change or remove that rule first.",
        "planning_visibility_not_self": "A question cannot depend on itself.",
        "planning_questions_limits_order": "The lowest number must not be above the highest.",
        "planning_questions_whole_limits": WHOLE_LIMITS,
        "planning_questions_question_type_check": "Choose one of the listed types.",
    }
    if constraint in known:
        return known[constraint]
    if getattr(error, "pgcode", None) == "P0001" and getattr(diag, "message_primary", None):
        return diag.message_primary
    if getattr(error, "pgcode", None) == "55P03":
        return "Someone else is changing the planning questions right now. Try again in a moment."
    return "The database refused the change. Nothing was changed."


# ------------------------------------------------------------------------------------------ the database

def audit(cur, who, table, key, before, after, note=None):
    """Writes one row of the change history (planning_catalog_changes). who: (name, user id)."""
    cur.execute("""insert into public.planning_catalog_changes
      (actor,actor_user_id,table_name,row_key,before_row,after_row,note) values(%s,%s,%s,%s,%s,%s,%s)""",
                (who[0], who[1], table, psycopg2.extras.Json(key),
                 psycopg2.extras.Json(before) if before is not None else None,
                 psycopg2.extras.Json(after) if after is not None else None, note))


def changed_fields(before, after):
    """The names of the fields that differ between two versions of a row (the change history lists them)."""
    skip = {"updated_at", "created_at"}
    names = sorted((set(before or {}) | set(after or {})) - skip)
    return [name for name in names if (before or {}).get(name) != (after or {}).get(name)]


def row_state(row):
    """What an edit form was built from (the row's last change); a save from an older page is refused."""
    return str(row.get("updated_at") or "")


def update_row(cur, who, table, row_id, changes, key, note=None):
    """Updates one catalog row by id, with its change history row. Returns the new row (or the old one if nothing
    changed). key: the history row key, or a function of the row before the change that returns it."""
    ident = sql.Identifier(table)
    cur.execute(sql.SQL("select to_jsonb(t) as row from public.{} t where id=%s for update").format(ident), (row_id,))
    found = cur.fetchone()
    if not found:
        raise ValueError("This item no longer exists. Reload the page.")
    before = found["row"]
    changes = {name: value for name, value in changes.items() if before.get(name) != (plain_json(value))}
    if not changes:
        return before
    assignments = sql.SQL(",").join(sql.SQL("{}=%s").format(sql.Identifier(name)) for name in changes)
    cur.execute(sql.SQL("update public.{} t set {} where id=%s returning to_jsonb(t) as row").format(ident, assignments),
                [*changes.values(), row_id])
    after = cur.fetchone()["row"]
    audit(cur, who, table, key(before) if callable(key) else key, before, after, note)
    return after


def plain_json(value):
    """A Python value as to_jsonb shows it, to skip updates that change nothing."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def reorder(cur, who, table, parent_column, parent_id, row_id, direction, key_of):
    """Moves one row up or down among its siblings (renumbered 10, 20, 30, ...). Returns False at either end."""
    where = sql.SQL("true") if parent_column is None else sql.SQL("{}=%s").format(sql.Identifier(parent_column))
    args = () if parent_column is None else (parent_id,)
    cur.execute(sql.SQL("select id,display_order from public.{} where {} order by display_order,id for update")
                .format(sql.Identifier(table), where), args)
    ids = [row["id"] for row in cur.fetchall()]
    if row_id not in ids:
        raise ValueError("This item no longer exists. Reload the page.")
    index = ids.index(row_id)
    other = index - 1 if direction == "up" else index + 1
    if not 0 <= other < len(ids):
        return False
    ids[index], ids[other] = ids[other], ids[index]
    cur.execute(sql.SQL("select id,display_order from public.{} where id = any(%s)").format(sql.Identifier(table)), (ids,))
    current = {row["id"]: row["display_order"] for row in cur.fetchall()}
    for position, item in enumerate(ids, start=1):
        if current[item] != position * 10:
            update_row(cur, who, table, item, {"display_order": position * 10}, key_of, "Order changed")
    return True


def load_catalog(cur):
    """(sections, questions, rules). Each question has `answered`: how many saved answers it has."""
    cur.execute("select * from public.planning_question_sections order by display_order,id")
    sections = cur.fetchall()
    # The saved answers are counted once for all questions (one pass, using the 024 index), not per question.
    cur.execute("""select q.*,coalesce(a.answered,0) answered from public.planning_questions q
      left join (select question_key,count(*) answered from public.weekly_planning_answers group by question_key) a
        on a.question_key=q.question_key
      order by q.display_order,q.id""")
    questions = cur.fetchall()
    cur.execute("select * from public.planning_question_visibility_rules order by id")
    rules = cur.fetchall()
    return sections, questions, rules


def on_form(sections, questions):
    """Keys of the questions missionaries see: active, in an active section. A show/hide rule whose parent is not
    one of them is ignored by the portal's Weekly Planning (planning.CATALOG_SQL in portal-api, and the rules' read
    policy of migration 024 for everyone signed in)."""
    live = {section["id"] for section in sections if section["active"]}
    return {q["question_key"] for q in questions if q["active"] and q["section_id"] in live}


def quoted(names):
    """'“A”', '“A” and “B”', '“A”, “B” and “C”'."""
    names = [f"“{name}”" for name in names]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def rule_text(rule, labels, asked=None):
    """'“Question” is at least 2'; with asked (the keys on the form), says when the rule is ignored."""
    parent = labels.get(rule["parent_question_key"], rule["parent_question_key"])
    value = rule["comparison_value"]
    value = {"true": "Yes", "false": "No"}.get(str(value).lower(), value)
    text = f"“{parent}” {OPERATORS.get(rule['operator'], rule['operator'])} {value}"
    if asked is not None and rule["parent_question_key"] not in asked:
        text += f" (ignored while “{parent}” is not on the form)"
    return text


def saved_answers(count):
    """'1 saved answer', '3 saved answers'. Two whole sentences, so the portal catalog can give each language its
    plural forms."""
    return f"{count} saved answer" if count == 1 else f"{count} saved answers"
