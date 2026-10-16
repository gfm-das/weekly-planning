"""Round 16: the text of migration 058 (Referral archive and Rates deleted) and its rollback. No database (the run on a throw-away
database is in docs/handoff/round16/item8-dupes.md)."""
import unittest
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "portal-api" / "migrations"
UP = "058_delete_referral_archive_and_rates.sql"
DOWN = "058_delete_referral_archive_and_rates_rollback.sql"


class Migration058(unittest.TestCase):
    def setUp(self):
        self.up = (MIGRATIONS / UP).read_text(encoding="utf-8")
        self.down = (MIGRATIONS / DOWN).read_text(encoding="utf-8")

    def test_one_transaction_in_each_file(self):
        for text in (self.up, self.down):
            self.assertEqual(text.count("\nBEGIN;"), 1)
            self.assertEqual(text.count("\nCOMMIT;"), 1)

    def test_the_old_batches_are_deleted_and_the_kinds_go(self):
        self.assertIn("DELETE FROM public.roster_import_batches WHERE kind IN ('REFERRAL_ARCHIVE', 'RATES');", self.up)
        self.assertIn("array_remove(array_remove(kinds, 'REFERRAL_ARCHIVE'), 'RATES')", self.up)
        self.assertIn("ARRAY['REFERRAL_ARCHIVE', 'RATES']", self.down)

    def test_archetypal_health_no_longer_reads_the_mixed_view(self):
        view = self.up[self.up.index("CREATE OR REPLACE VIEW dashboards.archetype_area_week"):]
        view = view[:view.index("-- 3.")]
        self.assertNotIn("findechristus_referrals_week", view)
        self.assertIn("FROM dashboards.finding_area_week f\n          WHERE f.findechristus AND f.people_found > 0", view)
        # The view is replaced before the view it used is dropped.
        self.assertLess(self.up.index("CREATE OR REPLACE VIEW dashboards.archetype_area_week"),
                        self.up.index("DROP VIEW IF EXISTS dashboards.findechristus_referrals_week;"))

    def test_the_two_tables_and_three_views_are_dropped_and_the_batch_view_forgets_them(self):
        for line in ("DROP VIEW IF EXISTS dashboards.findechristus_referrals_week;", "DROP VIEW IF EXISTS dashboards.referral_archive_week;",
                     "DROP VIEW IF EXISTS dashboards.finding_rate_week;", "DROP TABLE IF EXISTS public.referral_archive_weeks;",
                     "DROP TABLE IF EXISTS public.finding_rate_weeks;"):
            self.assertIn(line, self.up)
        batches = self.up[self.up.index("CREATE OR REPLACE VIEW public.data_upload_week_batches"):]
        batches = batches[:batches.index("-- 4.")]
        self.assertNotIn("referral_archive_weeks", batches)
        self.assertNotIn("finding_rate_weeks", batches)
        self.assertIn("baptism_history_weeks", batches)  # Baptism history stays
        self.assertNotIn("DROP TABLE IF EXISTS public.baptism_history_weeks", self.up)

    def test_the_rollback_makes_everything_again_and_says_the_rows_do_not_come_back(self):
        for line in ("CREATE TABLE IF NOT EXISTS public.referral_archive_weeks", "CREATE TABLE IF NOT EXISTS public.finding_rate_weeks",
                     "CREATE VIEW dashboards.referral_archive_week", "CREATE VIEW dashboards.finding_rate_week",
                     "CREATE VIEW dashboards.findechristus_referrals_week", "CREATE OR REPLACE VIEW dashboards.archetype_area_week"):
            self.assertIn(line, self.down)
        self.assertIn("NOT come back", self.up)
        self.assertIn("NOT COME BACK", self.down)

    def test_no_positional_column_list_on_archetype_plan_rows(self):
        """A live database may have another column set in dashboards.archetype_plan_rows() (the 034 version has 19 columns, the baseline 17).
        `archetype_plan_rows(a, b, c ...)` after the function call renames columns by position and broke 058 on the real server
        (column reference "new_member_lessons" is ambiguous). The view must name the columns it needs instead."""
        import re
        for text in (self.up, self.down):
            self.assertRegex(text, r"FROM dashboards\.archetype_plan_rows\(\) archetype_plan_rows\s*\n")
            self.assertIsNone(re.search(r"archetype_plan_rows\(\)\s+(?:AS\s+)?\w+\s*\(", text),
                              "a positional alias list on dashboards.archetype_plan_rows() is back")

    def test_the_kind_constraint_is_found_by_content_not_by_name(self):
        for text in (self.up, self.down):
            self.assertNotIn("DROP CONSTRAINT roster_import_batches_kind_check", text)
            self.assertIn("pg_get_constraintdef(c.oid) LIKE '%''TRANSFER''%'", text)


if __name__ == "__main__":
    unittest.main()
