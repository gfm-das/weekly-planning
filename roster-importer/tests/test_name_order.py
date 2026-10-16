"""The Account Manager and Staff accounts lists are in A to Z order of the LAST name (SQL text checks, no database)."""
import inspect
import unittest

import account_manager
import staff_accounts


def squash(text):
    return " ".join(text.split())


class NameOrderTests(unittest.TestCase):
    def test_account_rows_sort_by_last_name_inside_the_area(self):
        src = squash(inspect.getsource(account_manager.account_rows))
        self.assertIn("order by z.name,d.name,a.name,lower(m.last_name),lower(coalesce(m.first_name,'')),m.id", src)
        self.assertNotIn("a.name,m.display_name", src)

    def test_send_list_sorts_by_last_name(self):
        src = squash(inspect.getsource(account_manager))
        self.assertIn("order by lower(m.last_name),lower(coalesce(m.first_name,'')),m.id", src)
        self.assertNotIn("order by m.display_name", src)

    def test_staff_sort_by_the_last_word_of_the_display_name(self):
        src = squash(inspect.getsource(staff_accounts))
        self.assertIn("order by lower(regexp_replace(trim(up.display_name), '^.*[[:space:]]', '')),lower(up.display_name),up.id", src)


if __name__ == "__main__":
    unittest.main()
