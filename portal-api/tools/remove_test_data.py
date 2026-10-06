"""Removes test entries (made while trying the portal and Beta) from the mission database, by id.

Nothing is built in: every item to remove is given on the command line, and the script removes exactly those or
nothing at all (one transaction). It uses the app's own rules wherever the app has them, and refuses anything that
is on a submitted or locked plan.

    python remove_test_data.py --as USER_ID [--dry-run] [--uploads DIR] ITEM [ITEM ...]

--as       The account the removal is done for: an active AP, President or Data Analyst (user_profiles.id). The
           app's rules (row-level security, the plan guards and the "added by mistake" functions of migration 023)
           are checked as this person, exactly as when they press Delete in the portal.
--dry-run  Do everything, print what would be removed, then undo it. Deletes no files.
--uploads  Where the portal keeps attachment files (default /data/uploads, as in the portal-api container).

ITEM is kind:id:
  new_member:ID        A New Member (new_members.id): public.delete_new_member_added_by_mistake (023), which also
                       removes their weekly rows and, for a New Member made by "Baptized", puts the friend back on
                       the baptismal date list. List such a New Member before the friend if both should go.
  baptismal_friend:ID  A friend with a baptismal date (baptismal_date_people.id):
                       public.delete_baptismal_date_person_added_by_mistake (023).
                       For both kinds, rows on drafts of earlier weeks (which 023 keeps, because such a plan may
                       have been submitted once) are removed first, through the same plan rules as a Delete in the
                       plan. A person who is on a submitted or locked plan is refused.
  high_potential:ID    A high-potential friend's row (weekly_high_potential_friends.id) on a draft plan.
  plan:ID              An empty draft plan (weekly_area_reports.id): no answers, notes, key indicator numbers or
                       people (rows without a person and without any answer do not count), never imported.
  event:UUID           A calendar event with its attachments and attendance (the Calendar's Delete).
  announcement:UUID    An announcement with its attachments and read receipts (the Announcements' Delete).
  attachment:UUID      One attachment of an event or announcement.
  push_subscription:ID One device's reminder subscription (portal.push_subscriptions.id).

Run it in the portal-api container (it has DATABASE_URL and the uploads volume):
    docker cp portal-api/tools/remove_test_data.py portal-api:/tmp/remove_test_data.py
    docker exec portal-api python /tmp/remove_test_data.py --as <user id> --dry-run event:<uuid> baptismal_friend:19
Exit status: 0 removed (or dry run passed), 1 refused (nothing removed), 2 wrong arguments.
People are printed with initials only; events and announcements with their title.
"""
import argparse
import json
import os
import sys
import uuid
from datetime import date
from pathlib import Path

import psycopg2
import psycopg2.errors
from psycopg2.extras import RealDictCursor

KINDS = ('new_member', 'baptismal_friend', 'high_potential', 'plan', 'event', 'announcement', 'attachment',
         'push_subscription')
UUID_KINDS = {'event', 'announcement', 'attachment'}
MANAGER_ROLES = {'AP', 'PRESIDENT', 'DATA_ADMIN'}
KPI_COLUMNS = ('friends_found_actual', 'friends_found_goal', 'lessons_with_friends_actual', 'lessons_with_friends_goal',
               'lessons_with_members_actual', 'lessons_with_members_goal', 'sacrament_attendance_actual',
               'sacrament_attendance_goal', 'first_time_sacrament_actual', 'baptismal_dates_actual',
               'baptismal_dates_goal', 'new_member_sacrament_actual', 'new_member_sacrament_goal',
               'follow_up_lessons_actual', 'follow_up_lessons_goal', 'baptisms_confirmations_actual',
               'baptisms_confirmations_goal')
# Answer columns of the weekly person rows: a row without a person counts as empty only if all of these are empty.
NEW_MEMBER_ANSWERS = ('lessons_actual', 'lessons_goal', 'pmg_lessons_percentage', 'how_are_they_doing',
                      'discussed_in_gemiko', 'gemiko_support_plan', 'next_ordinance', 'at_church_this_sunday',
                      'has_calling', 'has_aaronic_priesthood', 'has_melchizedek_priesthood', 'ministers_to_someone',
                      'ministered_to_by_someone', 'has_active_temple_recommend', 'visited_temple_for_baptisms',
                      'reading', 'praying', 'member_involvement')
FRIEND_ANSWERS = ('baptismal_date_set_on', 'current_baptismal_date', 'finding_source', 'reading', 'praying',
                  'at_church_this_sunday', 'keeping_commandments', 'member_involvement')


class Refused(Exception):
    """The item may not be removed; nothing is removed."""


def initials(name):
    return ' '.join(part[0] + '.' for part in str(name or '').split() if part) or '(no name)'


def parse_items(values):
    items, seen = [], set()
    for value in values:
        kind, sep, raw = value.partition(':')
        if not sep or kind not in KINDS:
            raise ValueError(f'"{value}" is not kind:id (kinds: {", ".join(KINDS)}).')
        try:
            ident = str(uuid.UUID(raw)) if kind in UUID_KINDS else int(raw)
        except ValueError:
            raise ValueError(f'"{value}": the id must be {"a UUID" if kind in UUID_KINDS else "a whole number"}.')
        if (kind, ident) in seen:
            raise ValueError(f'"{value}" is listed twice.')
        seen.add((kind, ident))
        items.append((kind, ident))
    return items


class Remover:
    def __init__(self, conn, user_id):
        self.conn = conn
        self.cur = conn.cursor(cursor_factory=RealDictCursor)
        self.user_id = user_id
        self.files = []

    # -- helpers -------------------------------------------------------------------------------------------------
    def one(self, sql, args=()):
        self.cur.execute(sql, args)
        return self.cur.fetchone()

    def all(self, sql, args=()):
        self.cur.execute(sql, args)
        return self.cur.fetchall()

    def as_user(self):
        """The signed-in person: the authenticated role with their claims, like a portal request."""
        claims = json.dumps({'sub': self.user_id, 'role': 'authenticated'})
        self.cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (claims,))
        self.cur.execute('SET LOCAL ROLE authenticated')

    def as_server(self):
        """The server connection (postgres, no signed-in person), as portal-api runs its own deletes."""
        self.cur.execute('RESET ROLE')
        self.cur.execute("SELECT set_config('request.jwt.claims', '', true)")

    def check_user(self):
        profile = self.one("""SELECT up.active, up.app_role, up.additional_roles FROM public.user_profiles up
                              WHERE up.id = %s""", (self.user_id,))
        if not profile or not profile['active']:
            raise Refused(f'--as {self.user_id}: no active account with this id.')
        roles = {profile['app_role'], *(profile['additional_roles'] or [])}
        if not roles & MANAGER_ROLES:
            raise Refused(f'--as {self.user_id}: this account is not an AP, President or Data Analyst.')

    def plans_of(self, table, column, ident):
        return self.all(f"""SELECT r.id, r.status, rw.sunday, rw.sunday < public.current_reporting_sunday() AS earlier
                            FROM public.{table} w
                            JOIN public.weekly_area_reports r ON r.id = w.weekly_area_report_id
                            JOIN public.reporting_weeks rw ON rw.id = r.reporting_week_id
                            WHERE w.{column} = %s ORDER BY rw.sunday, r.id""", (ident,))

    # -- people --------------------------------------------------------------------------------------------------
    def person(self, kind, ident):
        table, weekly, column, function = {
            'new_member': ('new_members', 'weekly_new_members', 'new_member_id', 'delete_new_member_added_by_mistake'),
            'baptismal_friend': ('baptismal_date_people', 'weekly_baptismal_date_friends', 'baptismal_date_person_id',
                                 'delete_baptismal_date_person_added_by_mistake'),
        }[kind]
        found = self.one(f'SELECT id, display_name FROM public.{table} WHERE id = %s', (ident,))
        if not found:
            raise Refused('not found (already removed?).')
        label = initials(found['display_name'])
        plans = self.plans_of(weekly, column, ident)
        kept = [p for p in plans if p['status'] != 'DRAFT']
        if kept:
            raise Refused(f'{label} is on a submitted or locked plan ({", ".join(str(p["id"]) for p in kept)}), '
                          'so the record is kept for the mission\'s reports.')
        self.as_user()
        earlier = [p['id'] for p in plans if p['earlier']]
        if earlier:
            # Drafts of earlier weeks: removed through the plan's own rules (row-level security and the plan guard).
            self.cur.execute(f'DELETE FROM public.{weekly} WHERE {column} = %s AND weekly_area_report_id = ANY(%s)',
                             (ident, earlier))
            if self.cur.rowcount != len(earlier):
                raise Refused(f'{label}: the rows on earlier drafts {earlier} could not be removed as this account.')
        self.cur.execute(f'SELECT public.{function}(%s) AS result', (ident,))
        restored = self.cur.fetchone()['result'] if kind == 'new_member' else None
        self.as_server()
        text = f'{label}'
        if plans:
            text += ', with the row(s) on draft plan(s) ' + ', '.join(f'{p["id"]} ({p["sunday"]:%d %b})' for p in plans)
        if restored:
            text += f'; friend {restored} is back on the baptismal date list'
        return text

    def high_potential(self, ident):
        row = self.one("""SELECT h.name, r.id AS plan_id, r.status, rw.sunday FROM public.weekly_high_potential_friends h
                          JOIN public.weekly_area_reports r ON r.id = h.weekly_area_report_id
                          JOIN public.reporting_weeks rw ON rw.id = r.reporting_week_id WHERE h.id = %s""", (ident,))
        if not row:
            raise Refused('not found (already removed?).')
        name = 'unnamed friend' if row['name'] == 'New High Potential' else initials(row['name'])
        if row['status'] != 'DRAFT':
            raise Refused(f'{name} is on submitted or locked plan {row["plan_id"]}, so it is kept.')
        self.as_user()
        self.cur.execute('DELETE FROM public.weekly_high_potential_friends WHERE id = %s', (ident,))
        removed = self.cur.rowcount
        self.as_server()
        if removed != 1:
            raise Refused(f'{name}: this account may not change plan {row["plan_id"]}.')
        return f'{name}, on draft plan {row["plan_id"]} ({row["sunday"]:%d %b})'

    def plan(self, ident):
        plan = self.one(f"""SELECT r.*, rw.sunday,
                              (SELECT count(*) FROM public.weekly_planning_answers a WHERE a.weekly_area_report_id = r.id) AS answers,
                              (SELECT count(*) FROM public.weekly_high_potential_friends h WHERE h.weekly_area_report_id = r.id) AS high_potentials,
                              (SELECT count(*) FROM public.weekly_new_members w WHERE w.weekly_area_report_id = r.id
                                 AND (w.new_member_id IS NOT NULL OR num_nonnulls({', '.join('w.' + c for c in NEW_MEMBER_ANSWERS)}) > 0)) AS new_members,
                              (SELECT count(*) FROM public.weekly_baptismal_date_friends w WHERE w.weekly_area_report_id = r.id
                                 AND (w.baptismal_date_person_id IS NOT NULL OR num_nonnulls({', '.join('w.' + c for c in FRIEND_ANSWERS)}) > 0)) AS friends,
                              (SELECT count(*) FROM public.weekly_new_members w WHERE w.weekly_area_report_id = r.id) +
                              (SELECT count(*) FROM public.weekly_baptismal_date_friends w WHERE w.weekly_area_report_id = r.id) AS empty_rows,
                              EXISTS (SELECT 1 FROM public.historical_planning_details d WHERE d.weekly_area_report_id = r.id) AS history
                            FROM public.weekly_area_reports r JOIN public.reporting_weeks rw ON rw.id = r.reporting_week_id
                            WHERE r.id = %s""", (ident,))
        if not plan:
            raise Refused('not found (already removed?).')
        if plan['status'] != 'DRAFT':
            raise Refused(f'plan {ident} is {plan["status"].lower()}, so it is kept.')
        content = [what for what, present in (
            ('answers', plan['answers']), ('high-potential friends', plan['high_potentials']),
            ('New Members', plan['new_members']), ('friends with a baptismal date', plan['friends']),
            ('key indicator numbers', any(plan[c] for c in KPI_COLUMNS)), ('notes', (plan['notes'] or '').strip()),
            ('imported history', plan['history'] or plan['import_batch_id'] or plan['historical_source_key'])) if present]
        if content:
            raise Refused(f'plan {ident} is not empty (it has {", ".join(content)}), so it is kept.')
        self.as_server()
        self.cur.execute('DELETE FROM public.weekly_area_reports WHERE id = %s AND status = %s', (ident, 'DRAFT'))
        extra = plan['empty_rows'] - plan['new_members'] - plan['friends']
        return (f'empty draft of area {plan["area_id"]}, week of {plan["sunday"]:%d %b %Y}'
                + (f', with {extra} empty row(s) without a person' if extra else ''))

    # -- portal records (the same statements as app.py's delete routes) ----------------------------------------------
    def event(self, ident):
        self.as_server()
        event = self.one('SELECT id, title, starts_at FROM portal.events WHERE id = %s FOR UPDATE', (ident,))
        if not event:
            raise Refused('not found (already removed?).')
        files = self.all('SELECT storage_name FROM portal.attachments WHERE event_id = %s', (ident,))
        attendance = self.one('SELECT count(*) AS n FROM portal.attendance WHERE event_id = %s', (ident,))['n']
        self.cur.execute('DELETE FROM portal.events WHERE id = %s', (ident,))
        self.files += [f['storage_name'] for f in files]
        return (f'"{event["title"]}" ({event["starts_at"]:%d %b %Y}), {len(files)} attachment(s), '
                f'{attendance} attendance record(s)')

    def announcement(self, ident):
        self.as_server()
        record = self.one('SELECT id, title FROM portal.announcements WHERE id = %s FOR UPDATE', (ident,))
        if not record:
            raise Refused('not found (already removed?).')
        files = self.all('SELECT storage_name FROM portal.attachments WHERE announcement_id = %s', (ident,))
        self.cur.execute('DELETE FROM portal.announcements WHERE id = %s', (ident,))
        self.files += [f['storage_name'] for f in files]
        return f'"{record["title"]}", {len(files)} attachment(s)'

    def attachment(self, ident):
        self.as_server()
        record = self.one('SELECT filename, storage_name FROM portal.attachments WHERE id = %s', (ident,))
        if not record:
            raise Refused('not found (already removed?).')
        self.cur.execute('DELETE FROM portal.attachments WHERE id = %s', (ident,))
        self.files.append(record['storage_name'])
        return f'"{record["filename"]}"'

    def push_subscription(self, ident):
        self.as_server()
        record = self.one('SELECT user_id FROM portal.push_subscriptions WHERE id = %s', (ident,))
        if not record:
            raise Refused('not found (already removed?).')
        self.cur.execute('DELETE FROM portal.push_subscriptions WHERE id = %s', (ident,))
        return f'a device of account {record["user_id"]}'

    def remove(self, kind, ident):
        if kind in ('new_member', 'baptismal_friend'):
            return self.person(kind, ident)
        return getattr(self, kind)(ident)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--as', dest='user_id', required=True, help='user id of an active AP, President or Data Analyst')
    parser.add_argument('--dry-run', action='store_true', help='show what would be removed, then undo it')
    parser.add_argument('--uploads', default='/data/uploads', help='folder of the stored attachment files')
    parser.add_argument('items', nargs='+', help='kind:id, e.g. event:<uuid> baptismal_friend:19')
    args = parser.parse_args(argv)
    try:
        user_id = str(uuid.UUID(args.user_id))
        items = parse_items(args.items)
    except ValueError as error:
        print(f'Nothing removed: {error}', file=sys.stderr)
        return 2

    conn = psycopg2.connect(os.environ['DATABASE_URL'], connect_timeout=8)
    conn.autocommit = False
    remover = Remover(conn, user_id)
    done, refused = [], []
    try:
        remover.cur.execute("SET LOCAL lock_timeout = '10s'")
        remover.check_user()
        for kind, ident in items:
            remover.cur.execute('SAVEPOINT item')
            try:
                done.append((kind, ident, remover.remove(kind, ident)))
                remover.cur.execute('RELEASE SAVEPOINT item')
            except (Refused, psycopg2.Error) as error:
                remover.cur.execute('ROLLBACK TO SAVEPOINT item')
                remover.as_server()
                message = error.diag.message_primary if isinstance(error, psycopg2.Error) and error.diag.message_primary else str(error)
                refused.append((kind, ident, message))
        if refused or args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    except Refused as error:
        conn.rollback()
        print(f'Nothing removed: {error}', file=sys.stderr)
        return 1
    finally:
        conn.close()

    for kind, ident, message in refused:
        print(f'REFUSED  {kind}:{ident}  {message}')
    if refused:
        print(f'Nothing removed: {len(refused)} of {len(items)} item(s) refused. Take them off the list or fix them, '
              'then run again.')
        return 1
    verb = 'Would remove' if args.dry_run else 'Removed'
    for kind, ident, message in done:
        print(f'{verb:<12} {kind}:{ident}  {message}')
    if args.dry_run:
        print(f'Dry run: {len(done)} item(s) checked, nothing changed.')
        return 0
    missing = 0
    for stored in remover.files:
        try:
            (Path(args.uploads) / stored).unlink(missing_ok=True)
        except OSError:
            missing += 1
    print(f'{len(done)} item(s) removed on {date.today():%d %b %Y}' + (
        f'; {len(remover.files)} stored file(s) deleted' if remover.files else '') + (
        f' ({missing} could not be deleted; remove them from {args.uploads} by hand)' if missing else '') + '.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
