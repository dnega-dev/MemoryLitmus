"""Minimal external-adapter example.

Run from the repository root:

    PYTHONPATH=src:. python3 -m memory_litmus run examples.custom_adapter:create_adapter

Real integrations should implement MemoryAdapter over an isolated test namespace.
This example subclasses the executable reference only to show discovery and
capability declaration without introducing a backing store.
"""
from memory_litmus.adapters import InMemoryAdapter
from memory_litmus.models import AdapterMetadata
from memory_litmus.profiles import get_profile


class ExampleCoreAdapter(InMemoryAdapter):
    """Example adapter advertising only the portable core profile."""

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name="example-core",
            version="1.0",
            capabilities=get_profile("core").required,
            description="Example module:factory adapter with core capabilities.",
        )


def create_adapter() -> ExampleCoreAdapter:
    """Factories must return a fresh, resettable instance."""
    return ExampleCoreAdapter()
