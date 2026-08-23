"""Typed records produced from sanitized browser connector captures."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class BrowserConnectorRecordKind(StrEnum):
    """Business-neutral connector record kinds."""

    CREATOR_PROFILE = "creator_profile"
    KNOWLEDGE_OBSERVATION = "knowledge_observation"
    CAMPAIGN_METRICS = "campaign_metrics"
    UNMAPPED_CAPTURE = "unmapped_capture"


@dataclass(frozen=True)
class NormalizedBrowserConnectorRecord:
    """A normalized record ready for later business-specific import adapters."""

    kind: BrowserConnectorRecordKind
    company_id: int
    source_event_id: int | None
    platform: str
    confidence: float
    record: dict[str, Any]
    source: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        data = asdict(self)
        data["kind"] = self.kind.value
        return data
