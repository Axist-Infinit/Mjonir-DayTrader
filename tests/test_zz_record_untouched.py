"""The repo's own forward record (record/, tracked and append-only) is never written by the suite. This file is
discovered last (unittest sorts the test files by name), so it compares record/ after every other test file ran
with what tests/_load.py saw when the first one loaded. Every writer (entry.py --record, ticket.py approve and
decline, record.py) is pointed at ${TRADER_RECORD_DIR}, a throwaway folder outside the repo."""

import os
import unittest

import _load


class RecordUntouched(unittest.TestCase):
    def test_the_repo_record_is_byte_for_byte_what_it_was(self):
        self.assertEqual(_load.record_snapshot(), _load.RECORD_BEFORE)
        self.assertIn(".gitkeep", _load.RECORD_BEFORE)

    def test_the_writers_point_outside_the_repo(self):
        d = os.path.realpath(os.environ["TRADER_RECORD_DIR"])
        self.assertFalse(d.startswith(os.path.realpath(_load.ROOT) + os.sep), d)


if __name__ == "__main__":
    unittest.main()
