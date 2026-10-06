"""The question "are these the same person?" on the check pages of uploads (Historical CSV and Data uploads > People).

question_card() is the card the check pages show while pairs of people are still open; /people/decide saves the
answers (people_match.save_decision) and goes back to the check. Apply stays closed until every pair is answered.
"""
from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, request

import database
import page
import people_match as match
import sign_in
from page import h

pages = Blueprint("people_pages", __name__)

REASONS = {"same_name_other_area": "Same name, but in different areas.",
           "alike_name": "Very alike names in the same area."}


def area_labels(cur):
    """{area id: 'Zone / Area'} of the signed-in manager's mission (names the people are in)."""
    cur.execute("""select a.id,z.name zone,a.name area from public.areas a join public.districts d on d.id=a.district_id
      join public.zones z on z.id=d.zone_id where z.mission_id=%s""", (sign_in.current_mission_id(),))
    return {r["id"]: f"{r['zone']} / {r['area']}" for r in cur.fetchall()}


def person_text(person, areas):
    """One person of a pair: name, area, and what is known (weeks seen, baptism date, stored or in the file)."""
    name = " ".join(x for x in (person["first"], person["last"]) if x)
    bits = [areas.get(person["area_id"], "?")]
    if person.get("baptism_date"):
        bits.append(f"baptized {person['baptism_date']}")
    if person.get("first_seen"):
        bits.append(f"in the file {person['first_seen']}" + (f" to {person['last_seen']}" if person["last_seen"] != person["first_seen"] else ""))
    bits.append("already stored" if person.get("stored_id") else "from this file")
    return f"<b>{h(name)}</b><br><span class='muted'>{h(' · '.join(bits))}</span>"


def question_card(questions, back, areas):
    """The card with one same / different choice per open pair. back: the check page to return to."""
    if not questions:
        return ""
    rows = []
    for q in questions:
        field = h("decide::" + "|".join(q["keys"]))
        rows.append(f"""<tr><td>{person_text(q['a'], areas)}</td><td>{person_text(q['b'], areas)}</td>
          <td class="muted">{h(REASONS[q['reason']])}</td>
          <td><label><input type="radio" name="{field}" value="same"> Same person</label><br>
          <label><input type="radio" name="{field}" value="different"> Different people</label></td></tr>""")
    return f"""<div class="card" id="people-questions"><div class="step">2c · People who may be the same</div>
      <h3>{len(questions)} pair(s) to check</h3>
      <p class="muted">Joining makes one record with all the weeks. Different people stay separate. Your answer is
      remembered for later uploads. Pairs you leave empty stay open and Apply stays closed.</p>
      <p class="actions"><button type="button" class="secondary" onclick="document.querySelectorAll('#people-questions input[value=same]').forEach(function(x){{x.checked=true}})">Mark every pair: same person</button>
      <button type="button" class="secondary" onclick="document.querySelectorAll('#people-questions input[value=different]').forEach(function(x){{x.checked=true}})">Mark every pair: different people</button>
      <span class="muted">(you can still change single pairs before saving)</span></p>
      <form action="/people/decide" method="post"><input type="hidden" name="back" value="{h(back)}">
      <div class="scroll"><table><thead><tr><th>Person</th><th>Other person</th><th>Why asked</th><th>Your answer</th></tr></thead>
      <tbody>{''.join(rows)}</tbody></table></div><p><button>Save answers &amp; recheck</button></p></form></div>"""


def safe_back(url, default="/uploads"):
    """Only a path of this site: /historical/review or /uploads/people/review."""
    parts = urlsplit(url or "")
    return url if url and not parts.scheme and not parts.netloc and url.startswith("/") and not url.startswith("//") else default


@pages.route("/people/decide", methods=["POST"])
def decide():
    """Saves the answers of a question card, then shows the check again."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    saved = 0
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            for field, answer in request.form.items():
                if not field.startswith("decide::") or answer not in ("same", "different"):
                    continue
                key_a, _, key_b = field[len("decide::"):].partition("|")
                saved += match.save_decision(cur, sign_in.current_mission_id(), key_a, key_b, answer == "same", sign_in.actor_name())
    flash(f"{saved} answer(s) saved.")
    return redirect(safe_back(request.form.get("back")))
