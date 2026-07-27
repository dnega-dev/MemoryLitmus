"""Runtime-checkable adapter protocol.

MemoryLitmus defines observable semantics. It does not prescribe a database,
embedding model, graph schema, or a universally correct memory policy.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional, Protocol, Sequence, runtime_checkable

from .models import (
    AdapterMetadata,
    AuditEvent,
    DeleteRequest,
    DeleteResult,
    MemoryRecord,
    PutRequest,
    QueryRequest,
    QueryResponse,
    Scope,
)


@runtime_checkable
class MemoryAdapter(Protocol):
    """Minimum synchronous boundary consumed by the conformance runner.

    ``now`` is supplied by the suite to make expiry, historical reads, and audit
    timestamps deterministic. Production adapters may translate it to their own
    clock or transaction-time mechanism.
    """

    def metadata(self) -> AdapterMetadata:
        ...

    def reset(self) -> None:
        ...

    def put(self, request: PutRequest, now: Optional[datetime] = None) -> MemoryRecord:
        ...

    def query(self, request: QueryRequest, now: Optional[datetime] = None) -> QueryResponse:
        ...

    def history(self, memory_id: str, scope: Scope) -> Sequence[MemoryRecord]:
        ...

    def delete(self, request: DeleteRequest, now: Optional[datetime] = None) -> DeleteResult:
        ...

    def audit_log(self, scope: Optional[Scope] = None) -> Sequence[AuditEvent]:
        ...

    def purge_expired(self, now: Optional[datetime] = None) -> Sequence[str]:
        ...


AdapterFactory = Callable[[], MemoryAdapter]
