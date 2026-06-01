"""
Pydantic schema for labelled SERP card candidates.

Lifted verbatim from 01-RESEARCH.md §"Pattern 7: labelled.jsonl schema" (lines 676-697).
No business logic — schema only.
"""

from pydantic import BaseModel, Field
from typing import Literal


class CandidateInput(BaseModel):
    """The card as it would arrive at the LLM step — exact shape the LLM sees."""

    title: str
    url: str
    snippet: str | None = None
    price_in_card: str | None = None  # e.g. "$ 8.500" — preserved as raw string from SERP


class LabelledCandidate(BaseModel):
    """One labelled SERP card, ready for prompt-regression eval."""

    id: str  # stable id, e.g. "serp01-card05"
    source_fixture: str  # "01-pelota_playera_quico.html"
    candidate: CandidateInput
    expected_is_product: bool
    expected_confidence_min: float = Field(ge=0.0, le=1.0)  # if model says < this, regression FAIL
    expected_store_hint: str | None = None
    expected_freshness_signal: Literal["live_marketplace", "static_catalog", "blog", "unknown"]
    expected_price_hint: float | None = None
    notes: str | None = None  # reasoning, in Spanish or English mix is fine
