"""
Freshness assessment module.
FRESH-01..04 requirements from 02-RESEARCH.md §Phase Requirements.
assess_freshness(candidate, verdict, extracted) → fresh value (True | None).
FRESH-04: no signal → fresh=None (NOT False — unknown is different from stale).
"""

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .llm import LLMVerdict

# FRESH-01: MELI hosts — visit returns 200 → fresh=True
MELI_HOSTS = frozenset(
    {
        "mercadolibre.com.ar",
        "www.mercadolibre.com.ar",
        "listado.mercadolibre.com.ar",
        "articulo.mercadolibre.com.ar",
        "mercadolibre.com",
        "www.mercadolibre.com",
    }
)

# Freshness window: 90 days
FRESHNESS_WINDOW_DAYS = 90


def _parse_date(date_str: str | None) -> datetime | None:
    """Try to parse a datePublished/dateModified string to a timezone-aware datetime."""
    if not date_str:
        return None
    # Try common ISO formats
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _is_host_meli(url: str) -> bool:
    """Return True if the URL's registered domain is a MELI domain."""
    try:
        from urllib.parse import urlparse

        netloc = urlparse(url).netloc.lower()
        # Strip www. prefix for comparison
        return any(netloc == h or netloc.endswith("." + h.lstrip("www.")) for h in MELI_HOSTS)
    except Exception:
        return False


def assess_freshness(
    candidate: dict,
    verdict: "LLMVerdict | None",
    extracted: dict | None,
) -> bool | None:
    """
    FRESH-01: MELI host + visit returned 200 → fresh=True.
    FRESH-02: datePublished or dateModified within 90 days → fresh=True.
    FRESH-03: blog freshness_signal → already dropped by LLM-05; no further assessment.
    FRESH-04: no signal → fresh=None (NOT False — represents unknown, not stale).
    Returns True (fresh), or None (unknown).
    """
    url = candidate.get("url", "")

    # Read freshness_signal from candidate dict — set by curate_candidates from
    # LLMVerdict.freshness_signal. The legacy `verdict` parameter is kept for
    # backwards compatibility but candidate is the source of truth post-curate.
    candidate_signal = candidate.get("freshness_signal") or (
        getattr(verdict, "freshness_signal", None) if verdict is not None else None
    )

    # FRESH-03: blog is already dropped by should_keep() / LLM-05; defense in depth
    if candidate_signal == "blog":
        return None

    # FRESH-01: MELI host + successful visit (200) → fresh=True
    if _is_host_meli(url) and not candidate.get("visit_failed") and not candidate.get("skip_dead"):
        return True

    # FRESH-02: datePublished or dateModified within 90 days → fresh=True
    # `extracted` may be the candidate dict itself (visit_one stores extracted
    # fields directly on the candidate via candidate.update(extracted)).
    source = extracted if extracted is not None else candidate
    date_str = source.get("date_modified") or source.get("datePublished")
    dt = _parse_date(date_str)
    if dt is not None:
        now = datetime.now(tz=timezone.utc)
        if now - dt <= timedelta(days=FRESHNESS_WINDOW_DAYS):
            return True

    # Live-marketplace signal (e.g., LLM identified a MELI/Tiendanube product page)
    if candidate_signal == "live_marketplace":
        return True

    # FRESH-04: no signal → fresh=None (not False)
    return None
