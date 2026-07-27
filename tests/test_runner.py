import unittest

from memory_litmus.adapters import (
    BrokenDedupAdapter,
    BrokenHardDeleteAdapter,
    BrokenIsolationAdapter,
    BrokenSecretAdapter,
    BrokenStaleGraphAdapter,
    InMemoryAdapter,
)
from memory_litmus.models import AdapterMetadata, Capability
from memory_litmus.profiles import PROFILES, get_profile
from memory_litmus.runner import CheckStatus, resolve_adapter_factory, run_conformance, validate_adapter


class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference_full = run_conformance(InMemoryAdapter, get_profile("full"))

    def test_reference_passes_full_profile(self):
        failures = [item for item in self.reference_full.results if item.status is CheckStatus.FAIL]
        self.assertEqual([], failures, [item.to_dict() for item in failures])
        self.assertTrue(self.reference_full.passed)

    def test_reference_runs_at_least_twenty_five_checks(self):
        self.assertGreaterEqual(self.reference_full.counts()["pass"], 25)

    def test_broken_dedup_is_detected(self):
        run = run_conformance(BrokenDedupAdapter, get_profile("core"))
        failed = {item.check_id for item in run.results if item.status is CheckStatus.FAIL}
        self.assertIn("dedup.stable_identity", failed)

    def test_broken_isolation_is_detected(self):
        run = run_conformance(BrokenIsolationAdapter, get_profile("core"))
        failed = {item.check_id for item in run.results if item.status is CheckStatus.FAIL}
        self.assertIn("isolation.user", failed)

    def test_broken_secret_scrubbing_is_detected(self):
        run = run_conformance(BrokenSecretAdapter, get_profile("core"))
        failed = {item.check_id for item in run.results if item.status is CheckStatus.FAIL}
        self.assertIn("secret.value", failed)

    def test_broken_hard_delete_is_detected(self):
        run = run_conformance(BrokenHardDeleteAdapter, get_profile("core"))
        failed = {item.check_id for item in run.results if item.status is CheckStatus.FAIL}
        self.assertIn("delete.hard", failed)

    def test_broken_stale_graph_is_detected_even_when_capability_optional(self):
        run = run_conformance(BrokenStaleGraphAdapter, get_profile("core"))
        failed = {item.check_id for item in run.results if item.status is CheckStatus.FAIL}
        self.assertIn("retrieval.stale_graph", failed)

    def test_missing_required_capability_fails(self):
        class DedupOnly(InMemoryAdapter):
            def metadata(self):
                base = super().metadata()
                return AdapterMetadata(base.name, base.version, frozenset({Capability.DEDUPLICATION}))

        run = run_conformance(DedupOnly, get_profile("core"))
        result = next(item for item in run.results if item.check_id == "isolation.user")
        self.assertIs(result.status, CheckStatus.FAIL)
        self.assertIn("required capability", result.message)

    def test_missing_optional_capability_skips(self):
        class CoreOnly(InMemoryAdapter):
            def metadata(self):
                base = super().metadata()
                return AdapterMetadata(base.name, base.version, get_profile("core").required)

        run = run_conformance(CoreOnly, get_profile("core"))
        result = next(item for item in run.results if item.check_id == "audit.lifecycle")
        self.assertIs(result.status, CheckStatus.SKIP)
        self.assertIn("optional capability", result.message)

    def test_builtin_factory_resolution(self):
        self.assertIs(resolve_adapter_factory("reference"), InMemoryAdapter)

    def test_unknown_adapter_rejected(self):
        with self.assertRaises(ValueError):
            resolve_adapter_factory("does-not-exist")

    def test_protocol_validation_rejects_incomplete_adapter(self):
        with self.assertRaises(TypeError):
            validate_adapter(object())

    def test_profiles_do_not_overlap_required_and_optional(self):
        for profile in PROFILES.values():
            self.assertFalse(profile.required.intersection(profile.optional))

    def test_full_profile_requires_every_capability(self):
        self.assertEqual(frozenset(Capability), get_profile("full").required)


if __name__ == "__main__":
    unittest.main()
