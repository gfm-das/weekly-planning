"""Archetypal Health: the calculation behind portal/archetypes.html.

What it is: plain Python with no Flask and no database: it scores the areas, checks settings and picks the diagnosis
texts. Its functions only take numbers and give numbers back, so tests/test_archetypes.py can check them by hand.
Who uses it: archetypes.py, which loads the rows and serves the pages.

The model, as in the owner's sheet "Mission Benchmarks & Archetype Engine" ("Weighted profiles, then standardized
within peer groups"):

1. Each number (a KPI, e.g. New People Being Taught) of an area is averaged over the chosen weeks (weeks to average).
2. It is compared with the mission's usual week: z = (value - mission average) / mission standard deviation, where the
   mission average and deviation use every area-week up to the week shown ("all time" in the sheet).
3. Each archetype blends its KPIs with the weights (they add up to 100 %): profile = sum(weight x z) / sum(weight).
   A KPI without numbers is left out and the other weights count proportionally more ("re-normalised").
4. The profile is compared with what similar areas usually do (the peer group: same urban type, assignment type and
   density band): score = (profile - peer average) / peer standard deviation, where the peer average and deviation
   use the weekly profiles of every area-week of the group up to the week shown. An area whose group is too small is
   compared with the whole mission instead (every area of the mission, not only the other small-group areas).
   Because the comparison is with the group's usual week, a whole zone (or the mission) can be above or below 100 in
   a given week.
5. Index = 100 + 15 x score. 100 = what similar areas usually do, 115 = one standard deviation above, 85 = one below.
   Overall = the average of the six archetype indices.
6. Label: "Stalled" when every archetype is below 100; "Balanced" when the strongest is ahead of the next one by the
   balance threshold (0.2 standard deviations) or less; otherwise the strongest archetype.
A district, zone or the mission shows the average of its areas.

Standard deviations are sample deviations (n - 1), like STDEV in Google Sheets. A deviation of 0 (everyone the same)
gives a score of 0, i.e. an index of 100.
"""
import copy
import math
import re
from datetime import timedelta

ARCHETYPES = ('finding', 'teaching', 'bringing', 'baptizing', 'fellowshipping', 'reactivating')
WEEK_CHOICES = (1, 4, 8, 12)
BAND_COUNT = 5
MISSING = 'Missing'          # a peer-group attribute that is not known for an area
WHOLE_MISSION = 'Whole mission'
TREND_WEEKS = 8

# Every number the archetypes can use: the key is the column of dashboards.archetype_area_week (migration 034), the
# label is what people read (Preach My Gospel names for the key indicators), group says where it comes from.
SOURCES = {
    'friends_found': ('New People Being Taught', 'plans'),
    'lessons_with_friends': ('Lessons with friends', 'plans'),
    'follow_up_lessons': ('Follow-up lessons', 'plans'),
    'members_at_lessons': ('Lessons with a Member Participating', 'plans'),
    'baptismal_dates': ('People with a Baptismal Date', 'plans'),
    'baptisms_confirmations': ('People Who Are Baptized and Confirmed', 'plans'),
    'sacrament_attendance': ('People Being Taught Who Attend Sacrament Meeting', 'plans'),
    'first_time_sacrament': ('First time at sacrament meeting', 'plans'),
    'first_time_first_week_sacrament': ('At sacrament meeting the week they were found', 'answers'),
    'new_member_sacrament': ('New Members Attending Sacrament Meeting', 'plans'),
    'new_member_sacrament_share': ('Share of new members at sacrament meeting', 'new_members'),
    'new_member_lessons_per_member': ('Lessons per new member', 'new_members'),
    'member_meals_active': ('Member meals with active members', 'answers'),
    'member_meals_less_active': ('Member meals with less-active members', 'answers'),
    'member_meals_part_member': ('Member meals with part-member families', 'answers'),
    'member_visits_active': ('Member visits with active members', 'answers'),
    'member_visits_less_active': ('Member visits with less-active members', 'answers'),
    'member_visits_part_member': ('Member visits with part-member families', 'answers'),
    'member_referral_asks': ('Referral requests at member meals and visits', 'answers'),
    'lessons_asked_referral': ('Lessons where you asked for a referral', 'answers'),
    'facebook_finding_days': ('Days of Facebook finding', 'answers'),
    'facebook_friends_found': ('People found through Facebook', 'answers'),
    'youth_activities': ('Youth activities', 'answers'),
    'service_hours': ('Service hours', 'answers'),
    'less_active_sacrament': ('Less-active members at sacrament meeting', 'answers'),
    'findechristus_referrals': ('FindeChristus referrals', 'uploads'),
    'finding_people_found': ('People found (Church finding report)', 'uploads'),
    'finding_people_reached': ('People reached (Church finding report)', 'uploads'),
    'finding_first_lessons': ('First lessons (Church finding report)', 'uploads'),
    'baptism_records': ('Baptisms (baptism records)', 'uploads'),
}

# Archived numbers (migration 038, Oct 2026: Facebook, social media and FindeChristus are archived). They stay in
# SOURCES, so saved settings and their history that weight them stay valid and keep their labels, and old weeks keep
# their numbers. But the settings page no longer offers them, and a save cannot weight one in an archetype that did
# not weight it before (archived_added).
ARCHIVED_SOURCES = frozenset({'facebook_finding_days', 'facebook_friends_found', 'findechristus_referrals'})
# Archived diagnosis tips: no longer in the defaults; migration 038 takes them out of saved settings too.
ARCHIVED_STEPS = ('Follow up on FindeChristus referrals within a day.',)

# Peer-group attributes an area can have (dashboards.archetype_area_profile). Free extra attributes typed in
# DA Management are offered as 'extra:<name>'.
PEER_ATTRIBUTES = ('urban_type', 'assignment_type', 'density')

# Diagnosis patterns, in the order they are tried. Each has a title, what it usually means and 2-3 next steps.
PATTERNS = ('stalled', 'finding_low_teaching_strong', 'finding_strong_bringing_low', 'teaching_strong_baptizing_low',
            'baptizing_strong_fellowshipping_low', 'finding_low', 'teaching_low', 'bringing_low', 'baptizing_low',
            'fellowshipping_low', 'reactivating_low', 'balanced', 'steady')
MAX_PATTERNS = 2
MAX_STRENGTHS = 2

# The owner's sheet (read 29 Sep 2026): weight matrix, peer filters, bands, balance threshold and weeks to average.
# Every English text below is also in portal/i18n/catalogs.json (archetypes.*), so it is translated while unchanged.
DEFAULT_SETTINGS = {
    'weights': {
        'finding': {'friends_found': 45, 'lessons_with_friends': 20, 'follow_up_lessons': 10,
                    'sacrament_attendance': 5, 'first_time_first_week_sacrament': 20},
        'teaching': {'lessons_with_friends': 30, 'follow_up_lessons': 35, 'members_at_lessons': 25,
                     'baptismal_dates': 10},
        'bringing': {'sacrament_attendance': 20, 'first_time_first_week_sacrament': 50, 'first_time_sacrament': 30},
        'baptizing': {'baptismal_dates': 45, 'baptisms_confirmations': 55},
        'fellowshipping': {'new_member_sacrament_share': 55, 'new_member_lessons_per_member': 45},
        'reactivating': {'members_at_lessons': 5, 'new_member_lessons_per_member': 5, 'member_meals_active': 5,
                         'member_meals_less_active': 25, 'member_meals_part_member': 25, 'member_visits_active': 5,
                         'member_visits_less_active': 15, 'member_visits_part_member': 15},
    },
    'peer_group': {'attributes': ['urban_type', 'assignment_type', 'density'], 'density_bins': [200, 500, 700, 1200],
                   'minimum_size': 5, 'fallback': True},
    'bands': [
        {'from': 120, 'name': 'Outstanding', 'color': '#34b36a'},
        {'from': 110, 'name': 'Strong', 'color': '#a3e39a'},
        {'from': 90, 'name': 'Average', 'color': '#fff1c1'},
        {'from': 80, 'name': 'Needs attention', 'color': '#ffc49e'},
        {'from': None, 'name': 'High priority', 'color': '#ff9f9f'},
    ],
    'balance_threshold': 0.2,
    'weeks_to_average': 1,
    'diagnoses': {
        'strengths': {
            'finding': 'Creates and replenishes teaching opportunities.',
            'teaching': 'Strong, consistent teaching, and people are progressing.',
            'bringing': 'Brings friends and new members to church consistently.',
            'baptizing': 'Turns teaching into commitments and ordinances.',
            'fellowshipping': 'Strengthens and keeps new members close.',
            'reactivating': 'Helps less-active members come back and feel welcome.',
        },
        'patterns': {
            'stalled': {
                'title': 'A season to regroup',
                'meaning': 'This week every part of the work is below what similar areas usually see. It often means '
                           'the companions are tired, discouraged or facing something new, not that they are not trying.',
                'steps': ['Start by listening: ask the companions how they are doing and how you can help.',
                          'Plan together one simple goal for each day of the coming week.',
                          'Invite a member or the ward mission leader to join a lesson or a finding activity.']},
            'finding_low_teaching_strong': {
                'title': 'Teaching well, few new people',
                'meaning': 'The companions teach well, but few new people are coming in. Without new people to '
                           'teach, strong teaching slows down within a few weeks.',
                'steps': ['Thank them for their teaching, then plan daily finding time together.',
                          'Ask everyone they teach and every member they visit whom they know who would like to '
                          'hear the message.']},
            'finding_strong_bringing_low': {
                'title': 'Finding many, few at church',
                'meaning': 'Many new people are found, but few come to sacrament meeting. Coming to church early '
                           'helps people feel the Spirit and meet members.',
                'steps': ['Invite each new person to sacrament meeting in the first or second lesson.',
                          'Ask members to sit with them or bring them along.',
                          'Remind them kindly on Saturday and offer to meet them at the door.']},
            'teaching_strong_baptizing_low': {
                'title': 'Teaching well, few commitments',
                'meaning': 'Lessons are going well, but few people set or keep a baptismal date. People may need a '
                           'clear invitation and help to keep commitments.',
                'steps': ['Invite people to be baptized early, with a specific date.',
                          'Help each person keep one commitment at a time, and follow up soon.',
                          'Pray with the companions about each person\'s next step.']},
            'baptizing_strong_fellowshipping_low': {
                'title': 'New members need friends',
                'meaning': 'People are being baptized, but new members are not yet well connected. The first months '
                           'after baptism are when friends and teaching matter most.',
                'steps': ['Celebrate each baptism, then counsel with the ward council about every new member.',
                          'Keep teaching new members, with a member present.',
                          'Make sure each new member has ministering brothers or sisters.']},
            'finding_low': {
                'title': 'Help with finding',
                'meaning': 'Fewer new people are found than in similar areas. Finding is often easiest together '
                           'with members.',
                'steps': ['Plan daily finding time and try one new way to find this week.',
                          'Ask members whom they could invite to meet the missionaries.']},
            'teaching_low': {
                'title': 'Help with teaching',
                'meaning': 'Fewer lessons than in similar areas. People progress when they are taught regularly, '
                           'with members.',
                'steps': ['Set the next appointment at the end of every lesson.',
                          'Invite a member to join lessons this week.']},
            'bringing_low': {
                'title': 'Help with coming to church',
                'meaning': 'Fewer friends and new members at sacrament meeting than in similar areas.',
                'steps': ['Invite every person you teach to sacrament meeting and offer to go with them.',
                          'Ask members to sit with them and introduce them to others.']},
            'baptizing_low': {
                'title': 'Help with commitments',
                'meaning': 'Fewer baptismal dates and baptisms than in similar areas. Clear invitations and loving '
                           'follow-up help people move forward.',
                'steps': ['Invite people to be baptized, with a specific date.',
                          'Talk with the companions about what each person needs to keep their date.']},
            'fellowshipping_low': {
                'title': 'Help for new members',
                'meaning': 'New members are less connected than in similar areas: fewer lessons or fewer at church.',
                'steps': ['Keep teaching each new member, with a member present.',
                          'Counsel with the ward about a friend and a calling for each new member.']},
            'reactivating_low': {
                'title': 'Help with less-active members',
                'meaning': 'Fewer visits and meals with less-active members and part-member families than in '
                           'similar areas.',
                'steps': ['Ask the ward council which less-active members and part-member families to visit.',
                          'Plan visits and meals together with members.']},
            'balanced': {
                'title': 'An even balance',
                'meaning': 'No single strength stands out: the work is even across all its parts.',
                'steps': ['Thank the companions for their steady work.',
                          'Choose together one part of the work to grow in this month.']},
            'steady': {
                'title': 'Steady work',
                'meaning': 'Nothing is far below what similar areas usually see.',
                'steps': ['Thank the companions and ask what is going well.',
                          'Ask how you can help them keep going.']},
        },
    },
}


def defaults():
    """A fresh copy of the sheet's defaults (callers may change it)."""
    return copy.deepcopy(DEFAULT_SETTINGS)


# ---------------------------------------------------------------------------------------------------- checking settings

class SettingsError(ValueError):
    """Settings that cannot be saved. fields maps a place in the settings to a message people can read."""

    def __init__(self, fields):
        super().__init__('Please check the marked settings.')
        self.fields = fields


def _number(value):
    """A real number (not True/False, not NaN), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _text(value, limit):
    """Trimmed text of 1..limit characters, else None."""
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        return None
    return value.strip()


def _check_keys(value, expected, place, problems):
    """value must be a dict with exactly these keys."""
    if not isinstance(value, dict) or set(value) != set(expected):
        problems[place] = 'This part of the settings is incomplete.'
        return False
    return True


def check_weights(weights, problems):
    """Each archetype: known KPIs with whole-number weights from 1 to 100 that add up to exactly 100."""
    result = {}
    if not _check_keys(weights, ARCHETYPES, 'weights', problems):
        return result
    for archetype in ARCHETYPES:
        chosen = weights[archetype]
        place = 'weights.' + archetype
        if not isinstance(chosen, dict) or not chosen:
            problems[place] = 'Choose at least one number.'
            continue
        clean = {}
        for kpi, weight in chosen.items():
            if kpi not in SOURCES:
                problems[place] = 'This number is not available.'
            elif _number(weight) is None or weight != int(weight) or not 1 <= weight <= 100:
                problems[place] = 'Each weight is a whole number from 1 to 100.'
            else:
                clean[kpi] = int(weight)
        if place not in problems and sum(clean.values()) != 100:
            problems[place] = 'The weights must add up to 100 %.'
        result[archetype] = clean
    return result


def check_peer_group(peer, problems):
    """Which attributes make a peer group, the density bands, the smallest group and what happens below it."""
    if not _check_keys(peer, ('attributes', 'density_bins', 'minimum_size', 'fallback'), 'peer_group', problems):
        return {}
    attributes = peer['attributes']
    if not isinstance(attributes, list) or len(attributes) > 6 or len(set(map(str, attributes))) != len(attributes) \
            or any(not valid_attribute(a) for a in attributes):
        problems['peer_group.attributes'] = 'Choose the area details from the list.'
    bins = peer['density_bins']
    if not isinstance(bins, list) or not 1 <= len(bins) <= 8 or any(_number(b) is None or b <= 0 for b in bins) \
            or any(bins[i] >= bins[i + 1] for i in range(len(bins) - 1)):
        problems['peer_group.density_bins'] = 'Enter 1 to 8 limits above 0, from small to large.'
    size = peer['minimum_size']
    if _number(size) is None or size != int(size) or not 2 <= size <= 50:
        problems['peer_group.minimum_size'] = 'Enter a whole number from 2 to 50.'
    if not isinstance(peer['fallback'], bool):
        problems['peer_group.fallback'] = 'Choose yes or no.'
    return peer


def valid_attribute(value):
    """urban_type, assignment_type, density, or extra:<name> for a free attribute from DA Management."""
    if not isinstance(value, str):
        return False
    if value in PEER_ATTRIBUTES:
        return True
    return value.startswith('extra:') and 1 <= len(value[6:].strip()) <= 60


def check_bands(bands, problems):
    """Exactly five bands, highest first; each starts at a lower index than the one before; the last has no start."""
    if not isinstance(bands, list) or len(bands) != BAND_COUNT:
        problems['bands'] = 'There are always five bands.'
        return bands
    starts = [band.get('from') if isinstance(band, dict) else None for band in bands]
    if any(_number(value) is None or not 0 <= value <= 300 for value in starts[:-1]) or starts[-1] is not None \
            or any(starts[i] <= starts[i + 1] for i in range(len(starts) - 2)):
        problems['bands'] = 'Each band starts lower than the one above it (between 0 and 300).'
    for i, band in enumerate(bands):
        if not isinstance(band, dict) or set(band) != {'from', 'name', 'color'} or not _text(band['name'], 40):
            problems[f'bands.{i}'] = 'Give each band a name of up to 40 characters.'
        elif not isinstance(band['color'], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', band['color']):
            problems[f'bands.{i}'] = 'Choose a colour.'
    return bands


def check_diagnoses(diagnoses, problems):
    """Every strength text and every pattern's title, meaning and 1-3 next steps, with sensible lengths."""
    if not _check_keys(diagnoses, ('strengths', 'patterns'), 'diagnoses', problems):
        return
    if _check_keys(diagnoses['strengths'], ARCHETYPES, 'diagnoses.strengths', problems):
        for archetype, text in diagnoses['strengths'].items():
            if not _text(text, 300):
                problems['diagnoses.strengths.' + archetype] = 'Write up to 300 characters.'
    if not _check_keys(diagnoses['patterns'], PATTERNS, 'diagnoses.patterns', problems):
        return
    for key, pattern in diagnoses['patterns'].items():
        place = 'diagnoses.patterns.' + key
        if not _check_keys(pattern, ('title', 'meaning', 'steps'), place, problems):
            continue
        steps = pattern['steps']
        if not _text(pattern['title'], 80) or not _text(pattern['meaning'], 400):
            problems[place] = 'Write a title (up to 80 characters) and what it means (up to 400).'
        elif not isinstance(steps, list) or not 1 <= len(steps) <= 3 or any(not _text(s, 300) for s in steps):
            problems[place] = 'Write 1 to 3 next steps of up to 300 characters.'


def validate_settings(settings):
    """The settings as they will be saved (text trimmed), or SettingsError naming every problem."""
    problems = {}
    keys = ('weights', 'peer_group', 'bands', 'balance_threshold', 'weeks_to_average', 'diagnoses')
    if not _check_keys(settings, keys, 'settings', problems):
        raise SettingsError(problems)
    clean = copy.deepcopy(settings)
    clean['weights'] = check_weights(settings['weights'], problems)
    check_peer_group(settings['peer_group'], problems)
    check_bands(settings['bands'], problems)
    threshold = _number(settings['balance_threshold'])
    if threshold is None or not 0 <= threshold <= 2:
        problems['balance_threshold'] = 'Enter a number from 0 to 2.'
    if not is_week_choice(settings['weeks_to_average']):
        problems['weeks_to_average'] = 'Choose 1, 4, 8 or 12 weeks.'
    check_diagnoses(settings['diagnoses'], problems)
    if problems:
        raise SettingsError(problems)
    return trim_texts(clean)


def is_week_choice(value):
    """1, 4, 8 or 12 as a real whole number. Checked strictly because True == 1 and 4.0 == 4 in Python, and a saved
    4.0 would later break range() for everyone's page."""
    return isinstance(value, int) and not isinstance(value, bool) and value in WEEK_CHOICES


def trim_texts(value):
    """The same settings with spaces around every text removed."""
    if isinstance(value, dict):
        return {key: trim_texts(item) for key, item in value.items()}
    if isinstance(value, list):
        return [trim_texts(item) for item in value]
    return value.strip() if isinstance(value, str) else value


def archived_used(settings):
    """The archived numbers these settings weight, in any archetype."""
    weights = (settings or {}).get('weights') or {}
    return {kpi for chosen in weights.values() if isinstance(chosen, dict) for kpi in chosen if kpi in ARCHIVED_SOURCES}


def archived_added(before, after):
    """{'weights.<archetype>': message} for each archetype where `after` weights an archived number that `before`
    did not weight there. Lowering or removing such a weight is fine."""
    problems = {}
    old = (before or {}).get('weights') or {}
    for archetype, chosen in ((after or {}).get('weights') or {}).items():
        had = old.get(archetype) if isinstance(old.get(archetype), dict) else {}
        if isinstance(chosen, dict) and any(k in ARCHIVED_SOURCES and k not in had for k in chosen):
            problems['weights.' + archetype] = 'This number is archived and can no longer be added.'
    return problems


def change_summary(before, after):
    """A short English line for the change history: which parts changed."""
    parts = []
    for archetype in ARCHETYPES:
        if before['weights'].get(archetype) != after['weights'].get(archetype):
            parts.append('Weights: ' + archetype.title())
    if before['peer_group'] != after['peer_group']:
        parts.append('Peer groups')
    if before['bands'] != after['bands']:
        parts.append('Bands')
    for key, label in (('balance_threshold', 'Balance threshold'), ('weeks_to_average', 'Weeks to average')):
        if before[key] != after[key]:
            parts.append(f'{label}: {before[key]} → {after[key]}')
    if before['diagnoses'] != after['diagnoses']:
        parts.append('Diagnosis texts')
    return ', '.join(parts) or 'No change'


# ---------------------------------------------------------------------------------------------------- weeks

def week_list(rows):
    """{sunday: number of areas with a plan}, for every week in the rows."""
    counts = {}
    for row in rows:
        counts[row['sunday']] = counts.get(row['sunday'], 0) + 1
    return counts


def complete_weeks(counts, today):
    """Weeks whose Sunday has passed (a week is complete on the Monday after it), newest first."""
    return sorted((sunday for sunday in counts if sunday < today), reverse=True)


def default_week(counts, weeks):
    """The newest complete week with plans from at least half as many areas as the busiest week, so a week whose
    plans are still coming in is not shown first. None when there are no weeks."""
    if not weeks:
        return None
    busiest = max(counts[w] for w in weeks)
    return next(w for w in weeks if counts[w] * 2 >= busiest)


def window(week, weeks_to_average):
    """The Sundays of the weeks averaged for this week: the week itself and the ones just before it."""
    return {week - timedelta(days=7 * i) for i in range(weeks_to_average)}


# ---------------------------------------------------------------------------------------------------- statistics

def mean(values):
    """The average; None for no values."""
    return sum(values) / len(values) if values else None


def sample_sd(values):
    """Sample standard deviation (n - 1), like STDEV in Google Sheets. None with fewer than two values."""
    if len(values) < 2:
        return None
    average = mean(values)
    return math.sqrt(sum((v - average) ** 2 for v in values) / (len(values) - 1))


def z_score(value, average, sd):
    """How many standard deviations value is from average. 0 when everyone is the same (sd 0 or unknown)."""
    if value is None or average is None:
        return None
    if not sd:
        return 0.0
    return (value - average) / sd


def to_index(score):
    """100 + 15 x score: 100 = what similar areas usually do."""
    return None if score is None else 100 + 15 * score


# ---------------------------------------------------------------------------------------------------- the calculation

def used_kpis(settings):
    """Every KPI some archetype uses."""
    return sorted({kpi for weights in settings['weights'].values() for kpi in weights})


def kpis_with_data(rows, kpis, sundays):
    """The KPIs that have at least one number in these weeks (a KPI without any is skipped)."""
    found = set()
    for row in rows:
        if row['sunday'] in sundays:
            found.update(kpi for kpi in kpis if row.get(kpi) is not None)
    return found


def baseline(rows, kpis, until):
    """The mission's usual week for each KPI: (average, standard deviation) over every area-week up to 'until'."""
    values = {kpi: [] for kpi in kpis}
    for row in rows:
        if row['sunday'] <= until:
            for kpi in kpis:
                if row.get(kpi) is not None:
                    values[kpi].append(float(row[kpi]))
    return {kpi: (mean(v), sample_sd(v)) for kpi, v in values.items()}


def area_values(rows, kpis, sundays):
    """{area_id: {kpi: average over the chosen weeks}} for the areas with a plan in those weeks."""
    collected = {}
    for row in rows:
        if row['sunday'] in sundays:
            area = collected.setdefault(row['area_id'], {kpi: [] for kpi in kpis})
            for kpi in kpis:
                if row.get(kpi) is not None:
                    area[kpi].append(float(row[kpi]))
    return {area_id: {kpi: mean(v) for kpi, v in values.items()} for area_id, values in collected.items()}


def profile(kpi_z, weights, available):
    """One archetype's blend of KPI z-scores: sum(weight x z) / sum(weight), over the KPIs with a number. None when
    none of its KPIs has a number for this area."""
    used = {kpi: w for kpi, w in weights.items() if kpi in available and kpi_z.get(kpi) is not None}
    if not used:
        return None
    return sum(w * kpi_z[kpi] for kpi, w in used.items()) / sum(used.values())


def density_band(density, bins):
    """'< 200', '200 – 500', ..., '>= 1200' for the bins [200, 500, ..., 1200]; Missing when unknown."""
    if density is None:
        return MISSING
    density = float(density)
    if density < bins[0]:
        return f'< {bins[0]:g}'
    for low, high in zip(bins, bins[1:]):
        if density < high:
            return f'{low:g} – {high:g}'
    return f'>= {bins[-1]:g}'


def attribute_value(area, attribute, bins):
    """One peer-group attribute of an area, as text (Missing when unknown)."""
    if attribute == 'density':
        return density_band(area.get('density_per_km2'), bins)
    if attribute.startswith('extra:'):
        value = (area.get('extra') or {}).get(attribute[6:])
    else:
        value = area.get(attribute)
    return str(value).strip() if value not in (None, '') else MISSING


def peer_key(area, peer):
    """The peer group of an area, e.g. 'City | Standard | 700 – 1200'. No attributes: the whole mission."""
    if not peer['attributes']:
        return WHOLE_MISSION
    return ' | '.join(attribute_value(area, a, peer['density_bins']) for a in peer['attributes'])


def peer_groups(area_ids, attributes, peer):
    """{area_id: group name}: similar areas together; a group smaller than the minimum becomes the whole mission
    (fallback on: compared with every area, see peer_usual) or None (fallback off: those areas get no index)."""
    raw = {area_id: peer_key(attributes.get(area_id, {}), peer) for area_id in area_ids}
    sizes = {}
    for key in raw.values():
        sizes[key] = sizes.get(key, 0) + 1
    fallback = WHOLE_MISSION if peer['fallback'] else None
    return {area_id: key if sizes[key] >= peer['minimum_size'] or key == WHOLE_MISSION else fallback
            for area_id, key in raw.items()}


def label_for(scores, threshold):
    """'stalled', 'balanced', an archetype, or None when nothing is known."""
    known = sorted(((s, a) for a, s in scores.items() if s is not None), reverse=True)
    if not known:
        return None
    if all(s < 0 for s, _ in known):
        return 'stalled'
    if len(known) > 1 and known[0][0] - known[1][0] <= threshold:  # no strength stands out by MORE than it
        return 'balanced'
    return known[0][1]


def summary(scores, threshold):
    """Indices, overall and label from archetype scores."""
    indices = {a: to_index(scores.get(a)) for a in ARCHETYPES}
    present = [v for v in indices.values() if v is not None]
    return {'indices': indices, 'overall': mean(present), 'label': label_for(scores, threshold)}


def profiles_of(values, base, settings, available):
    """{archetype: profile} for one set of KPI values (one area-week, or an area's average over the chosen weeks)."""
    kpi_z = {kpi: z_score(values.get(kpi), *base[kpi]) for kpi in base}
    return {a: profile(kpi_z, settings['weights'][a], available) for a in ARCHETYPES}


def peer_usual(rows, groups, base, settings, available, until):
    """{group: {archetype: (average, standard deviation)}}: what similar areas usually do, over every week of theirs
    up to 'until' (the sheet's "peer-group expectation"). So 100 is the peer group's usual week, and a whole zone or the
    mission can be above or below it in a given week.

    Every area-week also goes into the 'Whole mission' bucket, whatever its own group: an area whose group is too small
    is compared with ALL areas, not only with the other areas left over from small groups."""
    collected = {}
    for row in rows:
        if row['sunday'] > until or row['area_id'] not in groups:
            continue
        weekly = profiles_of({k: None if row.get(k) is None else float(row[k]) for k in base}, base, settings, available)
        buckets = [WHOLE_MISSION]
        own_group = groups[row['area_id']]  # None: too small a group and no fallback
        if own_group not in (None, WHOLE_MISSION):
            buckets.append(own_group)
        for archetype, value in weekly.items():
            if value is None:
                continue
            for bucket in buckets:
                collected.setdefault(bucket, {}).setdefault(archetype, []).append(value)
    return {group: {a: (mean(v), sample_sd(v)) for a, v in by_archetype.items()}
            for group, by_archetype in collected.items()}


def standardize(profiles, groups, usual):
    """{area_id: {archetype: score}}: each area's profile compared with its peer group's usual week."""
    scores = {}
    for area_id, area_profiles in profiles.items():
        group_usual = usual.get(groups.get(area_id), {})
        scores[area_id] = {a: z_score(area_profiles[a], *group_usual.get(a, (None, None))) for a in ARCHETYPES}
    return scores


def score_week(rows, attributes, settings, week, weeks_to_average):
    """Every area's archetypes for one week. Returns {'areas': {area_id: {...}}, 'skipped': [kpi, ...]}."""
    kpis = used_kpis(settings)
    sundays = window(week, weeks_to_average)
    available = kpis_with_data(rows, kpis, sundays)
    base = baseline(rows, kpis, week)
    values = area_values(rows, kpis, sundays)
    profiles = {area_id: profiles_of(area, base, settings, available) for area_id, area in values.items()}
    groups = peer_groups({r['area_id'] for r in rows if r['sunday'] <= week}, attributes, settings['peer_group'])
    scores = standardize(profiles, groups, peer_usual(rows, groups, base, settings, available, week))
    areas = {}
    for area_id in values:
        areas[area_id] = summary(scores[area_id], settings['balance_threshold'])
        areas[area_id].update(scores=scores[area_id], peer_group=groups[area_id], values=values[area_id],
                              profiles=profiles[area_id])
    return {'areas': areas, 'skipped': sorted(set(kpis) - available)}


def roll_up(area_results, area_ids, threshold):
    """A district, zone or the mission: the average of its areas' scores (and so of their indices)."""
    scores = {}
    for archetype in ARCHETYPES:
        values = [area_results[a]['scores'][archetype] for a in area_ids
                  if a in area_results and area_results[a]['scores'][archetype] is not None]
        scores[archetype] = mean(values)
    result = summary(scores, threshold)
    overall = [area_results[a]['overall'] for a in area_ids if a in area_results and area_results[a]['overall'] is not None]
    result['overall'] = mean(overall)
    result['areas_scored'] = len(overall)
    return result


# ---------------------------------------------------------------------------------------------------- the diagnosis

def band_start(settings, name_index):
    """The index where band number name_index starts (0 = Outstanding ... 3 = Needs attention)."""
    return settings['bands'][name_index]['from']


def matching_patterns(indices, label, strong_from, low_below):
    """The diagnosis patterns that fit, most specific first. strong = at or above the Strong band; low = below the
    Average band."""
    def strong(a):
        return indices.get(a) is not None and indices[a] >= strong_from

    def low(a):
        return indices.get(a) is not None and indices[a] < low_below

    found = []
    if label == 'stalled':
        found.append('stalled')
    explained = set()  # low archetypes already explained by a two-part pattern
    for combo, weak, good in (('finding_low_teaching_strong', 'finding', 'teaching'),
                              ('finding_strong_bringing_low', 'bringing', 'finding'),
                              ('teaching_strong_baptizing_low', 'baptizing', 'teaching'),
                              ('baptizing_strong_fellowshipping_low', 'fellowshipping', 'baptizing')):
        if low(weak) and strong(good):
            found.append(combo)
            explained.add(weak)
    lowest_first = sorted((indices[a], a) for a in ARCHETYPES if low(a) and a not in explained)
    found.extend(a + '_low' for _, a in lowest_first)
    if label == 'balanced':
        found.append('balanced')
    if not found:
        found.append('steady')
    return found[:MAX_PATTERNS]


def diagnosis(result, settings):
    """What the details (▾) of an area show: its strengths first, then up to two patterns with next steps. An area
    without any index (no numbers, or no peer group) gets no pattern: the page then says there is not enough to compare,
    instead of claiming "steady work" that was never measured."""
    indices = result['indices']
    texts = settings['diagnoses']
    if all(v is None for v in indices.values()):
        return {'strengths': [], 'patterns': []}
    strengths = sorted(((v, a) for a, v in indices.items() if v is not None and v >= 100), reverse=True)
    patterns = matching_patterns(indices, result['label'], band_start(settings, 1), band_start(settings, 2))
    return {
        'strengths': [{'archetype': a, 'text': texts['strengths'][a]} for _, a in strengths[:MAX_STRENGTHS]],
        'patterns': [dict(id=p, **texts['patterns'][p]) for p in patterns],
    }
