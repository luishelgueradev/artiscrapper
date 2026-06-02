"""
D2/D6/D8 invariant assertions.
Pattern 10 from 02-RESEARCH.md (lines 1205-1224).
LIFECYCLE NOTE: This file will be EXTENDED in plan 02-03 Task 2 with implementation bodies
for test_recycle_triggers. Wave-1 stubs remain importable/skippable until 02-03 fills them.
Do NOT add sentinel comments that would break additive edits.
"""
import subprocess
import sys

import pytest


def test_no_uvloop_installed():
    """D6: uvloop must not be importable in the runtime environment."""
    result = subprocess.run(
        [sys.executable, "-c", "import uvloop"],
        capture_output=True,
    )
    assert result.returncode != 0, "uvloop is installed — D6 foot-gun!"


def test_uvloop_absent_from_lock():
    """D6: uvloop must not appear in pyproject.toml or uv.lock."""
    result = subprocess.run(
        ["grep", "-rE", "uvloop", "pyproject.toml", "uv.lock"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0, f"uvloop found: {result.stdout}"


def test_no_persistent_context_in_codebase():
    """D8: launch_persistent_context must not appear in src/."""
    result = subprocess.run(
        ["grep", "-rn", "launch_persistent_context", "src/"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0, (
        f"D8 foot-gun: launch_persistent_context found:\n{result.stdout}"
    )


def test_d2_fallback_is_dropped():
    """D2: timeout fallback confidence=0.3 is BELOW <0.4 cut → dropped."""
    try:
        from src.artiscrapper.llm import LLMVerdict, should_keep
        v = LLMVerdict.fallback("timeout")
        assert v.confidence == 0.3
        assert not should_keep(v), "D2 foot-gun: fallback verdict must be dropped!"
    except ImportError:
        pytest.xfail("llm.py not yet implemented — will be filled by plan 02-02")


@pytest.mark.xfail(strict=False, reason="Wave 3: test_recycle_triggers filled by plan 02-03")
def test_recycle_triggers():
    """BROWSER-03: Recycle loop fires after BROWSER_RECYCLE_AFTER uses — stub until 02-03."""
    pytest.skip("Wave 3: filled by plan 02-03")
