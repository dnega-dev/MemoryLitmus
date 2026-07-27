import unittest
from datetime import datetime, timezone

from memory_litmus.adapters import InMemoryAdapter, scrub_text
from memory_litmus.models import PutRequest, QueryRequest, Scope
from memory_litmus.protocol import MemoryAdapter


SCOPE = Scope("u", "a", "p", "s")


class ModelTests(unittest.TestCase):
    def test_scope_requires_every_dimension(self):
        with self.assertRaises(ValueError):
            Scope("", "a", "p", "s")

    def test_put_requires_event_id(self):
        with self.assertRaises(ValueError):
            PutRequest("", SCOPE, "key", "value")

    def test_negative_ttl_is_rejected(self):
        with self.assertRaises(ValueError):
            PutRequest("event", SCOPE, "key", "value", ttl_seconds=-1)

    def test_naive_observed_at_is_rejected(self):
        with self.assertRaises(ValueError):
            PutRequest("event", SCOPE, "key", "value", observed_at=datetime(2025, 1, 1))

    def test_naive_as_of_is_rejected(self):
        with self.assertRaises(ValueError):
            QueryRequest(SCOPE, as_of=datetime(2025, 1, 1))

    def test_unknown_stream_is_rejected(self):
        with self.assertRaises(ValueError):
            QueryRequest(SCOPE, streams=("magic",))

    def test_adapter_matches_runtime_protocol(self):
        self.assertIsInstance(InMemoryAdapter(), MemoryAdapter)

    def test_reference_rejects_naive_clock(self):
        with self.assertRaises(ValueError):
            InMemoryAdapter().put(PutRequest("event", SCOPE, "key", "value"), now=datetime(2025, 1, 1))

    def test_scrubber_handles_aws_key_shape(self):
        secret = "AKIAABCDEFGHIJKLMNOP"
        self.assertNotIn(secret, scrub_text("key=" + secret))

    def test_scrubber_leaves_benign_text(self):
        value = "Ada prefers strong tea."
        self.assertEqual(value, scrub_text(value))


if __name__ == "__main__":
    unittest.main()
