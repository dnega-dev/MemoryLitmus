"""Deterministic fixture catalog shared by checks, tests, and the CLI."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Mapping, Tuple

from .models import Scope


BASE_TIME = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
PRIMARY_SCOPE = Scope("user-a", "agent-a", "project-a", "session-a")
OTHER_USER_SCOPE = Scope("user-b", "agent-a", "project-a", "session-a")
OTHER_AGENT_SCOPE = Scope("user-a", "agent-b", "project-a", "session-a")
OTHER_PROJECT_SCOPE = Scope("user-a", "agent-a", "project-b", "session-a")
OTHER_SESSION_SCOPE = Scope("user-a", "agent-a", "project-a", "session-b")


@dataclass(frozen=True)
class FixtureDescriptor:
    name: str
    capability: str
    description: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "capability": self.capability,
            "description": self.description,
        }


FIXTURES: Tuple[FixtureDescriptor, ...] = (
    FixtureDescriptor("repeated-fact", "deduplication", "Same scoped fact repeated under distinct events."),
    FixtureDescriptor("explicit-correction", "supersession", "Two versions joined by explicit supersedes linkage."),
    FixtureDescriptor("scoped-conflict", "scoped_conflicts", "Conflicting values preserved within and across exact scopes."),
    FixtureDescriptor("four-axis-isolation", "isolation", "User, agent, project, and session boundaries varied one at a time."),
    FixtureDescriptor("version-chain", "version_history", "Three chronological versions in one lineage."),
    FixtureDescriptor("linked-lineages", "linked_lineage_delete", "Two linked lineages with multiple versions."),
    FixtureDescriptor("hard-erasure", "hard_delete", "Hard deletion leaves neither retrieval nor history evidence."),
    FixtureDescriptor("historical-read", "time_aware_query", "Reads before and after a correction boundary."),
    FixtureDescriptor("stale-graph", "multi_stream_search", "Superseded graph node linked to an active neighbor."),
    FixtureDescriptor("stream-outage", "multi_stream_search", "Lexical, vector, and graph failures injected independently."),
    FixtureDescriptor("fusion-outage", "rank_fusion", "Rank-fusion failure with deterministic best-score fallback."),
    FixtureDescriptor("reranker-outage", "reranker_fallback", "Reranker error preserves the fused candidate ordering."),
    FixtureDescriptor("credential-shaped-text", "secret_scrubbing", "Secrets in value and nested metadata."),
    FixtureDescriptor("audit-lifecycle", "audit", "Create, deduplicate, supersede, delete, and TTL purge audit events."),
    FixtureDescriptor("retention-grades", "graded_retention", "Ephemeral, working, and durable default horizons."),
    FixtureDescriptor("ttl-boundary", "hard_ttl", "Record visible immediately before but not at expiration."),
    FixtureDescriptor("event-replay", "idempotent_replay", "Repeated and conflicting event identifiers."),
)


def at(**delta: int) -> datetime:
    return BASE_TIME + timedelta(**delta)


def fixture_map() -> Mapping[str, FixtureDescriptor]:
    return {fixture.name: fixture for fixture in FIXTURES}
