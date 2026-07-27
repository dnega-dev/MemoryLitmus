"""Named capability profiles used to grade rather than over-generalize adapters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Mapping

from .models import Capability, CapabilityLevel


@dataclass(frozen=True)
class CapabilityProfile:
    name: str
    description: str
    required: FrozenSet[Capability]
    optional: FrozenSet[Capability]

    def level(self, capability: Capability) -> CapabilityLevel:
        if capability in self.required:
            return CapabilityLevel.REQUIRED
        if capability in self.optional:
            return CapabilityLevel.OPTIONAL
        return CapabilityLevel.UNSUPPORTED

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "required": sorted(item.value for item in self.required),
            "optional": sorted(item.value for item in self.optional),
        }


ALL_CAPABILITIES = frozenset(Capability)
CORE_REQUIRED = frozenset(
    {
        Capability.DEDUPLICATION,
        Capability.SUPERSESSION,
        Capability.SCOPED_CONFLICTS,
        Capability.ISOLATION,
        Capability.VERSION_HISTORY,
        Capability.HARD_DELETE,
        Capability.SECRET_SCRUBBING,
        Capability.IDEMPOTENT_REPLAY,
    }
)
PRIVACY_REQUIRED = frozenset(
    {
        Capability.ISOLATION,
        Capability.HARD_DELETE,
        Capability.SECRET_SCRUBBING,
        Capability.AUDIT,
        Capability.HARD_TTL,
    }
)
RESILIENCE_REQUIRED = frozenset(
    {
        Capability.MULTI_STREAM_SEARCH,
        Capability.RANK_FUSION,
        Capability.RERANKER_FALLBACK,
        Capability.TIME_AWARE_QUERY,
    }
)

PROFILES: Mapping[str, CapabilityProfile] = {
    "core": CapabilityProfile(
        name="core",
        description="Portable identity, lifecycle, isolation, privacy, and replay semantics.",
        required=CORE_REQUIRED,
        optional=ALL_CAPABILITIES.difference(CORE_REQUIRED),
    ),
    "privacy": CapabilityProfile(
        name="privacy",
        description="Isolation, erasure, scrubbing, expiry, and auditable mutation behavior.",
        required=PRIVACY_REQUIRED,
        optional=ALL_CAPABILITIES.difference(PRIVACY_REQUIRED),
    ),
    "resilience": CapabilityProfile(
        name="resilience",
        description="Historical retrieval and graceful retrieval-pipeline degradation.",
        required=RESILIENCE_REQUIRED,
        optional=ALL_CAPABILITIES.difference(RESILIENCE_REQUIRED),
    ),
    "full": CapabilityProfile(
        name="full",
        description="Every MemoryLitmus capability is required.",
        required=ALL_CAPABILITIES,
        optional=frozenset(),
    ),
}


def get_profile(name: str) -> CapabilityProfile:
    try:
        return PROFILES[name]
    except KeyError:
        raise KeyError("unknown profile %r; choose from %s" % (name, ", ".join(sorted(PROFILES))))
