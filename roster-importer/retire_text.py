"""The English texts of DA Management > Delete retired (retire.py and retire_pages.py).

Every text a person sees on those pages comes from here, each under a key (retire.*) in the style of the portal's translation
catalog. {name} marks a value filled in on the page. Translation: DA Management loads the portal's i18n.js, which translates
these English texts on the page from portal/i18n/*.json (14 languages). Where the portal already had the same English text
('Zone', 'Rows'), the catalog keeps it under its own key. tests/test_retire_rules.py checks that every text is in the catalog.
"""
from html import escape

TEXT = {
    # The list
    "retire.title": "Delete retired places and questions",
    "retire.intro": "Delete a closed zone, district or area, or a retired Weekly Planning question, that is no longer needed, for example after a rename. You see what is attached to it first and can move its history onto the item that replaced it. A backup of the database is made before anything is deleted, and the whole step is one entry in Import history, where it can be undone.",
    "retire.places.title": "Closed places",
    "retire.places.none": "No place is closed. Close a place first in Places.",
    "retire.questions.title": "Retired questions",
    "retire.questions.none": "No question is retired. Retire a question first in Planning questions.",
    "retire.review": "Review and delete",
    "retire.link.places": "Delete a closed place for good",
    "retire.link.questions": "Delete a retired question for good",
    "retire.col.kind": "Kind",
    "retire.col.rows": "Rows",
    "retire.col.name": "Name",
    "retire.col.where": "Where",
    "retire.col.answers": "Saved answers",
    "retire.kind.zone": "Zone",
    "retire.kind.district": "District",
    "retire.kind.area": "Area",
    # What the tables hold (the impact preview groups the counts by it)
    "retire.cat.plans": "Weekly plans",
    "retire.cat.people": "People and assignments",
    "retire.cat.callins": "Call-ins",
    "retire.cat.history": "Uploaded numbers and history",
    "retire.cat.places": "Places inside it",
    "retire.cat.settings": "Its own settings",
    "retire.cat.other": "Other data",
    # A place
    "retire.place.titleZone": "Delete zone {name}",
    "retire.place.titleDistrict": "Delete district {name}",
    "retire.place.titleArea": "Delete area {name}",
    "retire.place.open": "It is still open. Close it first in Places: only a closed place can be deleted.",
    "retire.place.serving": "{count} missionary(ies) serve here now. Move them first (Account Manager or a roster upload).",
    "retire.place.attached": "What is attached to it",
    "retire.place.nothing": "Nothing is attached to it. It can be deleted.",
    "retire.place.settingsNote": "Its own settings (area data, Geo data, the wards it serves, remembered names) are removed with it; Undo puts them back.",
    "retire.place.mustMove": "Something is attached to it. Choose below where it moves to; it cannot be deleted before.",
    "retire.place.moveTitle": "Move what is attached onto",
    "retire.place.moveNone": "Do not move anything",
    "retire.place.moveHelp": "The place you choose takes over the plans, people, Call-ins and history. Where both have something for the same week or plan, nothing is moved and the check says so.",
    "retire.place.check": "Check",
    "retire.place.checkOk": "Check passed: {moved} rows move and {removed} settings rows are removed with it. Nothing has been changed yet.",
    "retire.place.checkFailed": "Check failed",
    "retire.place.answers": "Saved answers in those plans: {count}.",
    "retire.confirm.title": "Confirm",
    "retire.confirm.type": "Type the name {name} to confirm",
    "retire.confirm.backup": "A backup of the database is made first and named in Import history. If the backup fails, nothing is deleted.",
    "retire.confirm.button": "Back up and delete",
    "retire.back": "Back to Delete retired",
    # A question
    "retire.question.title": "Delete question {name}",
    "retire.question.active": "It is still on the form. Retire it first on the Planning questions page: only a retired question can be deleted.",
    "retire.question.locked": "It is locked: Dashboards, Call-ins, Presentations or Archetypal Health read it. It can never be deleted.",
    "retire.question.counts": "Saved answers: {answers}. Answer choices: {options}. Grid rows: {rows}. Show/hide rules that name it: {rules}.",
    "retire.question.partsNote": "Its answer choices, grid rows and the show/hide rules that name it are removed with it; Undo puts them back.",
    "retire.question.answersTitle": "What happens to the saved answers",
    "retire.question.moveTo": "Move them to the question",
    "retire.question.moveHelp": "Only questions of the same type that have all its answer choices and grid rows are offered. Where a plan already has an answer to that question, the answer there stays and this one is dropped.",
    "retire.question.deleteThem": "Delete the saved answers too (Undo puts them back)",
    "retire.question.checkOk": "Check passed: {moved} saved answers move, {deleted} are deleted, {parts} choices, rows and rules go with it. Nothing has been changed yet.",
    "retire.question.pick": "Choose…",
    # Done and errors
    "retire.done": "Deleted. The backup {backup} was made first. It is in Import history, where it can be undone.",
    "retire.error.nothing": "Nothing was deleted.",
    "retire.error.notAllowed": "You are not allowed to delete this. Sign in through the portal as a manager.",
    "retire.error.notFound": "That place is not in your mission.",
    "retire.error.typeName": "Type the name exactly as shown to confirm.",
    "retire.error.badSuccessor": "That is not a place it can move to: it must be open, of the same kind and in your mission.",
    "retire.error.sameInBoth": "Both have data for the same week or plan in {what}, so it cannot be moved without losing one of them. Nothing was changed.",
    "retire.error.stillAttached": "Something is still attached to it: {what}. Nothing was changed.",
    "retire.error.unsupported": "{what} points at it in a way this page cannot undo, so it was not deleted. Ask the person who runs the system.",
    "retire.error.database": "The database refused the change: {problem}. Nothing was changed.",
    "retire.error.backup": "The backup could not be made, so nothing was deleted: {problem}",
    "retire.error.questionGone": "That question does not exist.",
    "retire.error.badQuestion": "That question cannot take these answers.",
    "retire.error.answersLeft": "It has saved answers. Move them to another question, or tick that they are deleted too.",
}


def plain(key, **values):
    """The English text of a key with its {values} filled in, as plain text (for messages and errors)."""
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
