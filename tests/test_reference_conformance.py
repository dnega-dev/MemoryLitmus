"""Expose every executable conformance check as a distinct unittest case."""
import re
import unittest

from memory_litmus.adapters import InMemoryAdapter
from memory_litmus.checks import CHECKS


class ReferenceConformanceTests(unittest.TestCase):
    """The bundled reference adapter must satisfy every published semantic check."""


def _method_name(check_id):
    return "test_" + re.sub(r"[^a-zA-Z0-9_]+", "_", check_id)


def _make_test(check):
    def test(self):
        adapter = InMemoryAdapter()
        adapter.reset()
        check.function(adapter)

    test.__name__ = _method_name(check.id)
    test.__doc__ = check.title
    return test


for _check in CHECKS:
    setattr(ReferenceConformanceTests, _method_name(_check.id), _make_test(_check))


class CheckCatalogTests(unittest.TestCase):
    def test_catalog_contains_at_least_twenty_five_checks(self):
        self.assertGreaterEqual(len(CHECKS), 25)

    def test_check_ids_are_unique(self):
        self.assertEqual(len(CHECKS), len({check.id for check in CHECKS}))

    def test_every_check_has_fixture_and_title(self):
        self.assertTrue(all(check.fixture and check.title for check in CHECKS))


if __name__ == "__main__":
    unittest.main()
