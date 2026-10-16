"""Round 16: the text of migration 057 (Area data merged into Geo data) and its rollback. No database (the run on a throw-away
database is in docs/handoff/round16/item7.md)."""
import unittest
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "portal-api" / "migrations"


class Migration057(unittest.TestCase):
    def setUp(self):
        self.up = (MIGRATIONS / "057_one_area_geo_data.sql").read_text(encoding="utf-8")
        self.down = (MIGRATIONS / "057_one_area_geo_data_rollback.sql").read_text(encoding="utf-8")

    def test_one_transaction_in_each_file(self):
        for text in (self.up, self.down):
            self.assertEqual(text.count("\nBEGIN;"), 1)
            self.assertEqual(text.count("\nCOMMIT;"), 1)

    def test_the_figures_are_copied_before_the_table_is_dropped(self):
        self.assertLess(self.up.index("INSERT INTO public.area_geo_data"), self.up.index("DROP TABLE IF EXISTS public.area_profiles;"))
        self.assertIn("coalesce(g.population, excluded.population)", self.up)  # Geo data wins, an empty cell is filled

    def test_the_peer_group_view_reads_geo_data_with_the_same_columns(self):
        view = self.up[self.up.index("CREATE OR REPLACE VIEW dashboards.archetype_area_profile"):]
        view = view[:view.index("COMMENT ON VIEW")]
        self.assertIn("public.area_geo_data", view)
        self.assertNotIn("area_profiles", view)
        for column in ("AS density_per_km2", "AS urban_type", "AS assignment_type", "AS extra", "a.active"):
            self.assertIn(column, view)

    def test_old_area_data_batches_are_deleted_and_the_kind_goes(self):
        self.assertIn("DELETE FROM public.roster_import_batches WHERE kind = 'AREA_DATA';", self.up)
        self.assertIn("array_remove(kinds, 'AREA_DATA')", self.up)
        self.assertIn("kinds || 'AREA_DATA'::text", self.down)


if __name__ == "__main__":
    unittest.main()
