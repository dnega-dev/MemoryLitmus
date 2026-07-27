"""Public data model for MemoryLitmus adapters.

The model deliberately uses only Python's standard library and remains compatible
with Python 3.9. Datetimes crossing the adapter boundary must be timezone-aware.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple


class Capability(str, Enum):
    DEDUPLICATION = "deduplication"
    SUPERSESSION = "supersession"
    SCOPED_CONFLICTS = "scoped_conflicts"
    ISOLATION = "isolation"
    VERSION_HISTORY = "version_history"
    LINKED_LINEAGE_DELETE = "linked_lineage_delete"
    HARD_DELETE = "hard_delete"
    TIME_AWARE_QUERY = "time_aware_query"
    MULTI_STREAM_SEARCH = "multi_stream_search"
    RANK_FUSION = "rank_fusion"
    RERANKER_FALLBACK = "reranker_fallback"
    SECRET_SCRUBBING = "secret_scrubbing"
    AUDIT = "audit"
    GRADED_RETENTION = "graded_retention"
    HARD_TTL = "hard_ttl"
    IDEMPOTENT_REPLAY = "idempotent_replay"


class CapabilityLevel(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    UNSUPPORTED = "unsupported"


class RecordStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


class RetentionClass(str, Enum):
    EPHEMERAL = "ephemeral"
    WORKING = "working"
    DURABLE = "durable"


class DeleteMode(str, Enum):
    SOFT = "soft"
    HARD = "hard"


class DeleteCascade(str, Enum):
    SELF = "self"
    LINEAGE = "lineage"
    LINKED_LINEAGE = "linked_lineage"


@dataclass(frozen=True)
class Scope:
    """Exact tenant boundary used by the reference semantics.

    Adapters may internally support hierarchical scopes, but a conformance query
    must not cross any of these four dimensions unless the contract is explicitly
    extended outside this suite.
    """

    user_id: str
    agent_id: str
    project_id: str
    session_id: str

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Scope.%s must be a non-empty string" % name)

    def key(self) -> Tuple[str, str, str, str]:
        return (self.user_id, self.agent_id, self.project_id, self.session_id)

    def to_dict(self) -> Dict[str, str]:
        return dict(asdict(self))


@dataclass(frozen=True)
class AdapterMetadata:
    name: str
    version: str
    capabilities: FrozenSet[Capability]
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "capabilities": sorted(capability.value for capability in self.capabilities),
        }


@dataclass(frozen=True)
class PutRequest:
    event_id: str
    scope: Scope
    fact_key: str
    value: str
    observed_at: Optional[datetime] = None
    supersedes_id: Optional[str] = None
    links: Tuple[str, ...] = ()
    retention: RetentionClass = RetentionClass.WORKING
    ttl_seconds: Optional[int] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id must be non-empty")
        if not self.fact_key.strip():
            raise ValueError("fact_key must be non-empty")
        if self.ttl_seconds is not None and self.ttl_seconds < 0:
            raise ValueError("ttl_seconds cannot be negative")
        ensure_aware(self.observed_at, "observed_at")


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    lineage_id: str
    version: int
    scope: Scope
    fact_key: str
    value: str
    status: RecordStatus
    created_at: datetime
    valid_from: datetime
    valid_to: Optional[datetime]
    expires_at: Optional[datetime]
    retention: RetentionClass
    supersedes_id: Optional[str]
    superseded_by_id: Optional[str]
    links: Tuple[str, ...]
    metadata: Mapping[str, Any]
    source_event_id: str
    deleted_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "lineage_id": self.lineage_id,
            "version": self.version,
            "scope": self.scope.to_dict(),
            "fact_key": self.fact_key,
            "value": self.value,
            "status": self.status.value,
            "created_at": isoformat(self.created_at),
            "valid_from": isoformat(self.valid_from),
            "valid_to": isoformat(self.valid_to),
            "expires_at": isoformat(self.expires_at),
            "retention": self.retention.value,
            "supersedes_id": self.supersedes_id,
            "superseded_by_id": self.superseded_by_id,
            "links": list(self.links),
            "metadata": dict(self.metadata),
            "source_event_id": self.source_event_id,
            "deleted_at": isoformat(self.deleted_at),
        }


@dataclass(frozen=True)
class QueryRequest:
    scope: Scope
    text: str = ""
    fact_key: Optional[str] = None
    as_of: Optional[datetime] = None
    limit: int = 10
    streams: Tuple[str, ...] = ("lexical", "vector", "graph")
    fail_streams: FrozenSet[str] = frozenset()
    fail_fusion: bool = False
    use_reranker: bool = False
    fail_reranker: bool = False

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("limit must be positive")
        ensure_aware(self.as_of, "as_of")
        allowed = {"lexical", "vector", "graph"}
        unknown = set(self.streams).difference(allowed)
        if unknown:
            raise ValueError("unknown search streams: %s" % sorted(unknown))
        unknown_failures = set(self.fail_streams).difference(allowed)
        if unknown_failures:
            raise ValueError("unknown failed streams: %s" % sorted(unknown_failures))


@dataclass(frozen=True)
class SearchHit:
    record: MemoryRecord
    score: float
    streams: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record": self.record.to_dict(),
            "score": self.score,
            "streams": list(self.streams),
        }


@dataclass(frozen=True)
class QueryResponse:
    hits: Tuple[SearchHit, ...]
    degraded_streams: Tuple[str, ...] = ()
    fusion_fallback: bool = False
    reranker_fallback: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hits": [hit.to_dict() for hit in self.hits],
            "degraded_streams": list(self.degraded_streams),
            "fusion_fallback": self.fusion_fallback,
            "reranker_fallback": self.reranker_fallback,
        }


@dataclass(frozen=True)
class DeleteRequest:
    event_id: str
    scope: Scope
    memory_id: str
    mode: DeleteMode = DeleteMode.SOFT
    cascade: DeleteCascade = DeleteCascade.SELF
    deleted_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.memory_id.strip():
            raise ValueError("event_id and memory_id must be non-empty")
        ensure_aware(self.deleted_at, "deleted_at")


@dataclass(frozen=True)
class DeleteResult:
    deleted_ids: Tuple[str, ...]
    mode: DeleteMode
    replayed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "deleted_ids": list(self.deleted_ids),
            "mode": self.mode.value,
            "replayed": self.replayed,
        }


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    operation: str
    timestamp: datetime
    subject_ids: Tuple[str, ...]
    scope: Scope
    outcome: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "operation": self.operation,
            "timestamp": isoformat(self.timestamp),
            "subject_ids": list(self.subject_ids),
            "scope": self.scope.to_dict(),
            "outcome": self.outcome,
            "details": dict(self.details),
        }


def ensure_aware(value: Optional[datetime], field_name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("%s must be timezone-aware" % field_name)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
