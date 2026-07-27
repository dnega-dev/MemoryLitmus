import json
import unittest
import xml.etree.ElementTree as ET

from memory_litmus.adapters import BrokenDedupAdapter, InMemoryAdapter
from memory_litmus.profiles import get_profile
from memory_litmus.reporters import render_json, render_junit, render_sarif, render_text
from memory_litmus.runner import run_conformance


class ReporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.passing = run_conformance(InMemoryAdapter, get_profile("core"))
        cls.failing = run_conformance(BrokenDedupAdapter, get_profile("core"))

    def test_text_report_has_summary_and_check_ids(self):
        text = render_text(self.passing)
        self.assertIn("CONFORMANT", text)
        self.assertIn("dedup.stable_identity", text)

    def test_text_report_marks_failure(self):
        text = render_text(self.failing)
        self.assertIn("NON-CONFORMANT", text)
        self.assertIn("[FAIL]", text)

    def test_json_report_is_machine_readable(self):
        payload = json.loads(render_json(self.passing))
        self.assertEqual("1.0", payload["schema_version"])
        self.assertTrue(payload["passed"])
        self.assertEqual(len(self.passing.results), len(payload["results"]))

    def test_junit_report_is_valid_xml(self):
        root = ET.fromstring(render_junit(self.passing))
        self.assertEqual("testsuites", root.tag)
        self.assertEqual(str(len(self.passing.results)), root.attrib["tests"])

    def test_junit_report_contains_failure_node(self):
        root = ET.fromstring(render_junit(self.failing))
        self.assertIsNotNone(root.find(".//failure"))

    def test_sarif_report_has_2_1_schema(self):
        payload = json.loads(render_sarif(self.passing))
        self.assertEqual("2.1.0", payload["version"])
        self.assertEqual("MemoryLitmus", payload["runs"][0]["tool"]["driver"]["name"])

    def test_sarif_failure_uses_error_level(self):
        payload = json.loads(render_sarif(self.failing))
        errors = [result for result in payload["runs"][0]["results"] if result["level"] == "error"]
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
