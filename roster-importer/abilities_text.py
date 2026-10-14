"""The English texts of DA Management > Accounts > Role abilities (abilities.py and abilities_page.py).

Every text a person sees on that page comes from here, each under a key (abil.*) in the style of the portal's translation catalog.
{name} marks a value filled in on the page. Translation: DA Management loads the portal's i18n.js, which translates these English
texts on the page from portal/i18n/*.json (14 languages); where the portal already had the same English text the catalog keeps it
under its own key (the role names, "Role", "What saving will change"). tests/test_abilities.py checks that every text is in every
catalog. Role names and ability names are shown as texts of their own (a table cell each), never glued into a sentence, so each
one is translated.
"""
from html import escape

TEXT = {
    # The menu entry and the page
    "abil.title": "Role abilities",
    "abil.intro": "Choose what each role may do. A switch can take a right away from a role and give it back. It never gives a role more than it has today, and it never widens who the role can see: a district leader still works only inside the district.",
    "abil.managersNote": "AP, President and Data Analyst always keep every ability, so nobody can be locked out. DA Management, giving roles, deleting places and this screen are not on the list: they stay with the managers and cannot be switched.",
    "abil.delay": "A saved change reaches every part of the system within 30 seconds.",
    "abil.builtIn": "The settings table is not in the database yet, or cannot be read. The built-in settings are in use and nothing can be changed here until it is there.",
    "abil.needPerson": "Sign in through the portal to change abilities: every change must name who made it.",
    "abil.denied": "Only the managers of the mission can open this page.",
    # The matrix
    "dam.role": "Role",
    "dam.whatSavingWillChange": "What saving will change",
    "abil.col.ability": "Ability",
    "abil.on": "On",
    "abil.off": "Off",
    "abil.alwaysOn": "Always on",
    "abil.alwaysOff": "Always off",
    "abil.preview": "Show what changes",
    # The abilities, in the order of the page: a name and a plain description
    "abil.ability.calendar.edit": "Edit the calendar",
    "abil.about.calendar.edit": "Add, change and delete calendar events, and record who attended.",
    "abil.ability.announcements.publish": "Publish announcements",
    "abil.about.announcements.publish": "Write announcements for the people of their own area (Office: for the whole mission).",
    "abil.ability.vollzogen.view": "See the Vollzogen list",
    "abil.about.vollzogen.view": "Open the list of people who were baptized and confirmed. It holds names.",
    "abil.ability.presentations.use": "Use Presentations",
    "abil.about.presentations.use": "Open the Presentations of their zone and the decks shared with them.",
    "abil.ability.plans.unlock": "Reopen submitted plans",
    "abil.about.plans.unlock": "Unlock a Weekly Planning plan that was submitted, inside their own district or zone.",
    # The preview ("What saving will change")
    "abil.nothing": "Nothing is switched differently from now.",
    "abil.col.now": "Now",
    "abil.col.after": "After saving",
    "abil.col.meaning": "What it means",
    "abil.effect.calendar.edit": "These people can no longer add, change or delete calendar events.",
    "abil.effect.announcements.publish": "These people can no longer publish announcements.",
    "abil.effect.vollzogen.view": "These people can no longer open the Vollzogen list.",
    "abil.effect.presentations.use": "These people can no longer open Presentations.",
    "abil.effect.plans.unlock": "These people can no longer reopen submitted plans.",
    "abil.effect.back": "These people get this ability back, inside their own area.",
    "abil.reason": "Reason (shown in the change log, optional)",
    "abil.typeChange": "Type CHANGE to confirm",
    "abil.save": "Save the change",
    "abil.back": "Back to the switches",
    # Messages
    "abil.saved": "Saved. The change reaches every part of the system within 30 seconds.",
    "abil.noChange": "Nothing was changed.",
    "abil.stale": "The settings were changed by someone else while you were looking. Review them again.",
    "abil.badWord": "Type CHANGE to confirm the change.",
    "abil.badCell": "That switch cannot be changed.",
    "abil.reverted": "Reverted.",
    "abil.revertStale": "Some of these switches were changed again since, so this cannot be reverted. Change them by hand.",
    "abil.revertDone": "This change was already reverted.",
    "abil.revertMissing": "That change was not found.",
    # The change log
    "abil.log.title": "Change log",
    "abil.log.empty": "Nothing has been changed yet. The table still holds the built-in settings.",
    "abil.log.when": "When",
    "abil.log.who": "Who",
    "abil.log.what": "Change",
    "abil.log.revert": "Revert this change",
    "abil.log.confirm": "Switch these back to how they were before?",
    "abil.log.isRevert": "A revert of an earlier change",
    "abil.log.wasReverted": "Reverted",
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
