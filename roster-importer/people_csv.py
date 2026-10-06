"""People in the old Weekly Planning form export: reading them out of the rows the import will write.

Each row of the export is one companionship's form for one Sunday. It holds up to 10 new members, 12 friends with a
baptismal date and 10 high-potential friends. people_of_rows() turns the rows of a checked upload (the "rows" of
historical_preview.preview) into the pieces people_match and people_write work with. Nothing is written here.
"""
import historical_import as historical
import people_match as match

# The new member answers, in the order historical_import.new_member_answers() returns them (after the name).
NEW_MEMBER_ANSWERS = ("gender", "age_range", "lessons_actual", "lessons_goal", "pmg_lessons_percentage", "next_ordinance",
                      "at_church_this_sunday", "has_calling", "has_aaronic_priesthood", "has_melchizedek_priesthood",
                      "ministers_to_someone", "ministered_to_by_someone", "has_active_temple_recommend",
                      "visited_temple_for_baptisms", "reading", "praying", "member_involvement", "how_are_they_doing",
                      "discussed_in_gemiko", "gemiko_support_plan")
WEEKLY_NEW_MEMBER = NEW_MEMBER_ANSWERS[2:]  # the answers that go on the weekly plan row


def people_of_rows(items):
    """(new members and friends as appearances, high-potential friends) of the rows an import would write.
    An appearance: kind, name, first, last, area_id, unit_id, sunday, order, target (the report it belongs to),
    profile (what is known about the person) and weekly (the answers of that week)."""
    appearances, high_potentials = [], []
    for item in items:
        row, area_id, unit_id, sunday = item["row"], item["area"]["id"], item["unit_id"], item["sunday"]
        target = (area_id, sunday, unit_id)
        for part in range(1, 11):
            name = historical.clean(historical.new_member_column(row, part, "First & Last Name pt.{part}"))
            if not name:
                continue
            first, last = match.split_name(name)
            answers = dict(zip(NEW_MEMBER_ANSWERS, historical.new_member_answers(row, part)))
            appearances.append({"kind": match.NEW_MEMBER, "name": name, "first": first, "last": last, "area_id": area_id,
                                "unit_id": unit_id, "sunday": sunday, "order": part, "target": target,
                                "baptism_date": None,
                                "profile": {"gender": answers["gender"], "age_range": answers["age_range"]},
                                "weekly": {k: answers[k] for k in WEEKLY_NEW_MEMBER}})
        for part in range(1, 13):
            first = historical.clean(row.get(f"First Name pt.{part}"))
            last = historical.clean(row.get(f"Last Name pt.{part}"))
            if not first and not last:
                continue
            both = historical.parse_boolean(row.get(f"Baptismal Date Friend Commitments pt.{part} [Reading and Praying?]"))
            commitments = f"Baptismal Date Friend Commitments pt.{part} ["
            appearances.append({
                "kind": match.FRIEND, "name": f"{first} {last}".strip(), "first": first or last, "last": last if first else None,
                "area_id": area_id, "unit_id": unit_id, "sunday": sunday, "order": part, "target": target, "baptism_date": None,
                "profile": {"finding_source": historical.clean(row.get(f"Finding Source, of friend on baptismal date pt.{part}")) or None},
                "weekly": {"baptismal_date_set_on": _date(row.get(f"When was the baptismal date set? pt.{part}")),
                           "current_baptismal_date": _date(row.get(f"For which date is their baptismal date currently set? pt.{part}")),
                           "reading": both, "praying": both,
                           "at_church_this_sunday": historical.parse_boolean(row.get(commitments + "Were they at church this Sunday?]")),
                           "keeping_commandments": historical.parse_boolean(row.get(commitments + "Keeping the Commandments?]")),
                           "member_involvement": historical.parse_boolean(row.get(commitments + "Member Involvement?]"))}})
        for part in range(1, 11):
            name = historical.clean(row.get(f"Optional: High potential {part}, first and last name"))
            if name:
                high_potentials.append({"target": target, "name": name, "order": part,
                                        "at_church_this_sunday": historical.parse_boolean(
                                            row.get(f"Optional: High potential {part}, were they at church?"))})
    return appearances, high_potentials


def _date(value):
    """A date from a cell, or None when it is empty or unreadable (the check of the dates is not this file's job)."""
    try:
        return historical.parse_source_date(value)
    except ValueError:
        return None
