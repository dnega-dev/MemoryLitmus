"""MemoryLitmus: conformance tests for agent-memory semantics."""
from .adapters import InMemoryAdapter
from .models import (
    AdapterMetadata,
    AuditEvent,
    Capability,
    CapabilityLevel,
    DeleteCascade,
    DeleteMode,
    DeleteRequest,
    DeleteResult,
    MemoryRecord,
    PutRequest,
    QueryRequest,
    QueryResponse,
    RecordStatus,
    RetentionClass,
    Scope,
    SearchHit,
)
from .profiles import CapabilityProfile
from .protocol import MemoryAdapter
from .runner import RunResult, run_adapter, run_conformance

__version__ = "0.1.0"

__all__ = [
    "AdapterMetadata",
    "AuditEvent",
    "Capability",
    "CapabilityLevel",
    "CapabilityProfile",
    "DeleteCascade",
    "DeleteMode",
    "DeleteRequest",
    "DeleteResult",
    "InMemoryAdapter",
    "MemoryAdapter",
    "MemoryRecord",
    "PutRequest",
    "QueryRequest",
    "QueryResponse",
    "RecordStatus",
    "RetentionClass",
    "RunResult",
    "Scope",
    "SearchHit",
    "run_adapter",
    "run_conformance",
]
