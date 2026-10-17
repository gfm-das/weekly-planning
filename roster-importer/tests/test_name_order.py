"""The Account Manager and Staff accounts lists start in A to Z order of the LAST name and sort by any column (no database)."""
import inspect
import unittest

import account_manager
import page
import staff_accounts


def squash(text):
    return " ".join(text.split())


class NameOrderTests(unittest.TestCase):
    def test_account_rows_sort_by_last_name(self):
        src = squash(inspect.getsource(account_manager.account_rows))
        self.assertIn("order by lower(m.last_name),lower(coalesce(m.first_name,'')),m.id", src)
        self.assertNotIn("order by z.name", src)

    def test_send_list_sorts_by_last_name(self):
        src = squash(inspect.getsource(account_manager))
        self.assertIn("order by lower(m.last_name),lower(coalesce(m.first_name,'')),m.id", src)
        self.assertNotIn("order by m.display_name", src)

    def test_staff_sort_by_the_last_word_of_the_display_name(self):
        src = squash(inspect.getsource(staff_accounts))
        self.assertIn("order by lower(regexp_replace(trim(up.display_name), '^.*[[:space:]]', '')),lower(up.display_name),up.id", src)


    def test_both_tables_are_sortable_and_start_by_last_name(self):
        for module, first in ((account_manager, "<th data-sort-default>Missionary</th>"), (staff_accounts, "<th data-sort-default>Name</th>")):
            src = inspect.getsource(module)
            self.assertIn('<table class="sortable">', src)
            self.assertIn(first, src)
        row = account_manager.table_row({"missionary_id": 7, "display_name": "Elder Özdemir", "missionary_number": "123", "last_name": "Özdemir",
                                         "first_name": "Ali", "email": None, "area": "Mainz", "district": "D", "zone": "Z", "roster_position_abbr": "",
                                         "leadership_roles": "", "account_roles": "", "account_status": "No email"})
        self.assertIn('data-sort="Özdemir Ali"', row)
        self.assertIn('data-sort=""', row)  # a missing email sorts last
        self.assertEqual(staff_accounts.last_name_first("President Max Muster"), "Muster President Max")
        self.assertEqual(staff_accounts.last_name_first(None), "")

    def test_the_page_script_sorts_with_buttons_aria_sort_and_empty_cells_last(self):
        for part in ('table.sortable', 'aria-sort', 'b.type="button"', 'Intl.Collator', 'sensitivity:"base",numeric:true', '(!x-!y)||dir*compare(x,y)'):
            self.assertIn(part, page.FRAME)
        self.assertIn("th[aria-sort=descending] .sort-arrow:after", page.STYLE)


if __name__ == "__main__":
    unittest.main()
