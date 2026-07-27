import io
import json
import unittest

from memory_litmus.cli import main


class CliTests(unittest.TestCase):
    def invoke(self, args):
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = main(args, stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_adapters_list(self):
        code, stdout, stderr = self.invoke(["adapters", "list"])
        self.assertEqual(0, code)
        self.assertIn("reference", stdout)
        self.assertIn("broken-dedup", stdout)
        self.assertEqual("", stderr)

    def test_adapters_list_json(self):
        code, stdout, _ = self.invoke(["adapters", "list", "--format", "json"])
        self.assertEqual(0, code)
        payload = json.loads(stdout)
        self.assertTrue(any(item["name"] == "reference" for item in payload["adapters"]))

    def test_profile_show(self):
        code, stdout, _ = self.invoke(["profile", "show", "privacy"])
        self.assertEqual(0, code)
        self.assertIn("Required:", stdout)
        self.assertIn("secret_scrubbing", stdout)

    def test_profile_show_json(self):
        code, stdout, _ = self.invoke(["profile", "show", "core", "--format", "json"])
        self.assertEqual(0, code)
        self.assertEqual("core", json.loads(stdout)["name"])

    def test_fixtures_list(self):
        code, stdout, _ = self.invoke(["fixtures", "list"])
        self.assertEqual(0, code)
        self.assertIn("repeated-fact", stdout)
        self.assertIn("stream-outage", stdout)

    def test_reference_run_returns_zero(self):
        code, stdout, stderr = self.invoke(["run", "reference", "--profile", "full"])
        self.assertEqual(0, code, stdout + stderr)
        self.assertIn("CONFORMANT", stdout)

    def test_broken_run_returns_one(self):
        code, stdout, _ = self.invoke(["run", "broken-dedup", "--profile", "core"])
        self.assertEqual(1, code)
        self.assertIn("NON-CONFORMANT", stdout)

    def test_json_run(self):
        code, stdout, _ = self.invoke(["run", "reference", "--format", "json"])
        self.assertEqual(0, code)
        self.assertTrue(json.loads(stdout)["passed"])

    def test_unknown_adapter_returns_configuration_error(self):
        code, stdout, stderr = self.invoke(["run", "unknown-adapter"])
        self.assertEqual(2, code)
        self.assertEqual("", stdout)
        self.assertIn("unknown adapter", stderr)


if __name__ == "__main__":
    unittest.main()
