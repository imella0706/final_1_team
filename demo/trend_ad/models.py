from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class TrendCard:
    card_id: str
    title: str
    source: str
    published_date: str = ""
    source_url: str = ""
    summary: str = ""
    context: str = ""
    signal: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def search_text(self) -> str:
        return " ".join(
            value
            for value in (self.title, self.summary, self.context)
            if value
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SearchResult:
    card: TrendCard
    score: float
    matched_terms: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "matched_terms": list(self.matched_terms),
            "reasons": list(self.reasons),
            "card": self.card.to_dict(),
        }


@dataclass(frozen=True)
class Scene:
    start: float
    end: float
    role: str
    on_screen_text: str
    visual_direction: str
    motion: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Storyboard:
    brief: str
    product: str
    audience: str
    cta: str
    trend: TrendCard
    duration_seconds: float
    aspect_ratio: str
    scenes: tuple[Scene, ...]
    generation_prompt: str
    negative_prompt: str
    rights_note: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["trend"] = self.trend.to_dict()
        data["scenes"] = [scene.to_dict() for scene in self.scenes]
        return data

