"""The Fact type — nothing leaves an engine without one.

PART 5.1. Three rules, enforced here rather than by convention:

1. Engines return ``dict[str, Fact]``, never bare numbers.
2. A derived Fact inherits the **lowest** confidence and the **coarsest**
   geo_level of its inputs. ``derive()`` does this automatically; doing it by
   hand is how a village-level claim ends up resting on a state-level price.
3. If ``geo_level`` is coarser than the question, ``note`` must be populated.
   ``Fact.__post_init__`` raises if it is not.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Iterable, Literal

GeoLevel = Literal["village", "subdistrict", "district", "state", "national"]
Confidence = Literal["high", "medium", "low"]

# Coarser = larger number. Used to pick the coarsest input.
GEO_ORDER: dict[str, int] = {
    "village": 0, "subdistrict": 1, "district": 2, "state": 3, "national": 4,
}
# Lower = worse. Used to pick the weakest input.
CONF_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2}
CONF_BY_RANK = {v: k for k, v in CONF_ORDER.items()}


@dataclass(frozen=True)
class Fact:
    value: float | int | str | None
    unit: str | None
    source: str
    year: int | None
    geo_level: GeoLevel
    confidence: Confidence
    note: str | None = None

    def __post_init__(self) -> None:
        if self.geo_level not in GEO_ORDER:
            raise ValueError(f"bad geo_level {self.geo_level!r}")
        if self.confidence not in CONF_ORDER:
            raise ValueError(f"bad confidence {self.confidence!r}")
        # PART 5.1: a non-village answer to a village question must say so.
        if self.geo_level != "village" and not self.note:
            raise ValueError(
                f"Fact at geo_level={self.geo_level!r} must carry a note "
                f"explaining the degradation (source={self.source!r})"
            )
        if isinstance(self.value, float) and (
            math.isnan(self.value) or math.isinf(self.value)
        ):
            raise ValueError(f"non-finite Fact value from {self.source!r}")

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "year": self.year,
            "geo_level": self.geo_level,
            "confidence": self.confidence,
            "note": self.note,
            "_fact": True,
        }

    def with_note(self, note: str) -> "Fact":
        return replace(self, note=note)


def worst_confidence(facts: Iterable[Fact]) -> Confidence:
    ranks = [CONF_ORDER[f.confidence] for f in facts]
    return CONF_BY_RANK[min(ranks)] if ranks else "low"


def coarsest_geo(facts: Iterable[Fact]) -> GeoLevel:
    levels = [(GEO_ORDER[f.geo_level], f.geo_level) for f in facts]
    return max(levels)[1] if levels else "national"  # type: ignore[return-value]


def derive(
    value: float | int | str | None,
    unit: str | None,
    source: str,
    *inputs: Fact,
    year: int | None = None,
    note: str | None = None,
    geo_level: GeoLevel | None = None,
    confidence: Confidence | None = None,
) -> Fact:
    """Build a Fact from other Facts, inheriting the weakest provenance.

    ``geo_level`` and ``confidence`` may be passed to force a value, but the
    forced value is only honoured if it is not *better* than what the inputs
    justify — you cannot launder a state-level input into a village claim.
    """
    inherited_geo = coarsest_geo(inputs) if inputs else (geo_level or "national")
    inherited_conf = worst_confidence(inputs) if inputs else (confidence or "low")

    if geo_level is not None:
        inherited_geo = max(
            (GEO_ORDER[geo_level], geo_level),
            (GEO_ORDER[inherited_geo], inherited_geo),
        )[1]
    if confidence is not None:
        inherited_conf = CONF_BY_RANK[
            min(CONF_ORDER[confidence], CONF_ORDER[inherited_conf])
        ]

    if year is None:
        years = [f.year for f in inputs if f.year is not None]
        year = min(years) if years else None

    # Carry forward why the answer is coarse than village, so the reason
    # survives all the way to the provenance panel instead of being
    # regenerated as a generic string.
    if inherited_geo != "village" and not note:
        culprits = [
            f for f in inputs if f.geo_level == inherited_geo and f.note
        ]
        if culprits:
            note = (
                f"Inherited {inherited_geo}-level provenance from: "
                f"{culprits[0].source}. {culprits[0].note}"
            )
        else:
            note = (
                f"Computed from {inherited_geo}-level inputs; "
                "no village-level data available."
            )
    return Fact(
        value=value, unit=unit, source=source, year=year,
        geo_level=inherited_geo, confidence=inherited_conf, note=note,
    )


def fact_from_yaml(d: dict, default_source: str = "sector template") -> Fact:
    """Build a Fact from a YAML block that already carries provenance fields."""
    return Fact(
        value=d["value"],
        unit=d.get("unit"),
        source=d.get("source", default_source),
        year=d.get("year"),
        geo_level=d.get("geo_level", "national"),
        confidence=d.get("confidence", "low"),
        note=d.get("note"),
    )


# ----------------------------------------------------------------------
# Envelope helpers
# ----------------------------------------------------------------------
def encode(obj: Any) -> Any:
    """Recursively turn Facts into dicts for JSON output."""
    if isinstance(obj, Fact):
        return obj.to_dict()
    if isinstance(obj, dict):
        return {k: encode(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [encode(v) for v in obj]
    return obj


# Keys whose numeric values are structural, not measurements, and so are
# legitimately allowed to be bare in the envelope.
_ALLOWED_BARE_KEYS = {
    "capital_inr", "run_id", "value", "year", "schema_version",
    "catchment_km", "safety_factor", "monte_carlo_runs", "seed",
}


def iter_bare_numbers(obj: Any, path: str = "") -> list[str]:
    """Find numeric leaves that are NOT inside a Fact. Powers test_no_bare_numbers.

    A dict carrying ``_fact: True`` is a serialised Fact; its interior is the
    provenance itself, so traversal stops there.
    """
    bad: list[str] = []
    if isinstance(obj, Fact):
        return bad
    if isinstance(obj, dict):
        if obj.get("_fact") is True:
            return bad
        # Policy constants (verdict thresholds and weights) are declared
        # parameters, not measurements. They are published in the envelope so
        # the verdict is auditable, and a threshold has no source/year/geo the
        # way an observation does. The subtree must opt in explicitly.
        if obj.get("_policy") is True:
            return bad
        # A citation is source metadata, not a measurement. Its page number is
        # a locator of the same kind as a Fact's own `year` — it points AT a
        # source rather than asserting a quantity about the world.
        if obj.get("_citation") is True:
            return bad
        for k, v in obj.items():
            if k in _ALLOWED_BARE_KEYS:
                continue
            bad += iter_bare_numbers(v, f"{path}.{k}" if path else str(k))
        return bad
    if isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            bad += iter_bare_numbers(v, f"{path}[{i}]")
        return bad
    if isinstance(obj, bool):
        return bad
    if isinstance(obj, (int, float)):
        bad.append(path)
    return bad


def flatten_provenance(obj: Any, path: str = "") -> list[dict]:
    """Every Fact used, flattened — the 'show me your sources' panel."""
    out: list[dict] = []
    if isinstance(obj, Fact):
        out.append({"path": path, **obj.to_dict()})
        return out
    if isinstance(obj, dict):
        if obj.get("_fact") is True:
            out.append({"path": path, **obj})
            return out
        for k, v in obj.items():
            out += flatten_provenance(v, f"{path}.{k}" if path else str(k))
        return out
    if isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out += flatten_provenance(v, f"{path}[{i}]")
    return out
