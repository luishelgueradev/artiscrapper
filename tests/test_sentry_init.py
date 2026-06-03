"""
D-14 / D-15 / D-16 / D-19 (WRN-04): Sentry SDK init gating + correlation tagging.

Tests (RED until Task 2 wires _init_sentry into logging_setup, plus Task 3
for the lifespan-log-matches-SDK-state WRN-04 alignment invariant):

  - test_no_init_when_dsn_empty: SENTRY_DSN="" → get_client().is_active() False
  - test_sample_rates: SENTRY_DSN set → sentry_sdk.init called with
    traces_sample_rate=0.1, profiles_sample_rate=0.0, send_default_pii=False
  - test_correlation_id_tag: add_correlation_id processor sets the
    `correlation_id` tag on the Sentry scope (D-16)
  - test_lifespan_log_matches_sdk_state: WRN-04 — the lifespan log event name
    (`sentry_init_done` / `sentry_init_skipped`) MUST match the boolean
    returned by `sentry_sdk.get_client().is_active()`. Captures structlog
    output via `structlog.testing.capture_logs` while booting the TestClient
    under both DSN-empty and DSN-set configurations.
"""

import importlib
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sentry_sdk

# Shared mock browser helper — duplicated from test_auth so this file is
# self-contained and the env-var-then-import order isn't disturbed.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ.setdefault("LLM_ROUTER_BEARER_TOKEN", "test-token-sentry")
os.environ["CACHE_DB_PATH"] = _tmp_db.name
os.environ.setdefault("API_KEYS", "test-key-1")


@pytest.fixture(autouse=True)
def _reset_sentry_client():
    """
    Reset the Sentry global client between tests so a prior test's
    `_init_sentry()` call doesn't leak into the next test's
    `get_client().is_active()` assertion. Uses Scope.set_client(None) which
    replaces the active client with a NonRecordingClient (sentry-sdk 2.x API).
    """
    yield
    # Tear down any active client BEFORE the next test reloads logging_setup.
    try:
        # Close the active client (flushes pending events with a quick timeout).
        client = sentry_sdk.get_client()
        if client.is_active():
            try:
                client.close(timeout=0.0)
            except Exception:
                pass
        # Replace with NonRecordingClient so is_active() returns False.
        sentry_sdk.get_current_scope().set_client(None)
        sentry_sdk.get_isolation_scope().set_client(None)
        sentry_sdk.get_global_scope().set_client(None)
    except Exception:
        pass


def _make_mock_browser() -> MagicMock:
    mock_page = AsyncMock()
    mock_page.evaluate = AsyncMock(return_value=1)
    mock_page.goto = AsyncMock(return_value=None)
    mock_page.close = AsyncMock()

    mock_ctx = AsyncMock()
    mock_ctx.new_page = AsyncMock(return_value=mock_page)
    mock_ctx.close = AsyncMock()

    browser = MagicMock()
    browser.is_connected.return_value = True
    browser.new_context = AsyncMock(return_value=mock_ctx)
    browser.close = AsyncMock()
    return browser


def test_no_init_when_dsn_empty(monkeypatch):
    """D-14: sentry_sdk.init must not configure a real client when DSN is empty."""
    monkeypatch.setenv("SENTRY_DSN", "")
    # Reload config so the new env var is picked up, then reload logging_setup
    # so its module-import-time _init_sentry runs against the empty DSN.
    from src.artiscrapper import config as cfg
    importlib.reload(cfg)
    from src.artiscrapper import logging_setup
    importlib.reload(logging_setup)

    client = sentry_sdk.get_client()
    assert not client.is_active(), (
        f"D-14: Sentry should be off when DSN is empty; got is_active()={client.is_active()}"
    )


def test_sample_rates(monkeypatch):
    """D-15: traces_sample_rate=0.1, profiles_sample_rate=0.0, send_default_pii=False."""
    monkeypatch.setenv("SENTRY_DSN", "https://fake@sentry.invalid/1")
    from src.artiscrapper import config as cfg
    importlib.reload(cfg)

    with patch("sentry_sdk.init") as mock_init:
        from src.artiscrapper import logging_setup
        importlib.reload(logging_setup)
        assert mock_init.called, "D-15: sentry_sdk.init must be called when DSN is set"
        kwargs = mock_init.call_args.kwargs
        assert kwargs.get("traces_sample_rate") == 0.1, (
            f"D-15: traces_sample_rate should be 0.1, got {kwargs.get('traces_sample_rate')}"
        )
        assert kwargs.get("profiles_sample_rate") == 0.0, (
            f"D-15: profiles_sample_rate should be 0.0, got {kwargs.get('profiles_sample_rate')}"
        )
        assert kwargs.get("send_default_pii") is False, (
            f"D-15: send_default_pii should be False, got {kwargs.get('send_default_pii')}"
        )


def test_correlation_id_tag(monkeypatch):
    """D-16: add_correlation_id processor must set tags.correlation_id on Sentry scope."""
    monkeypatch.setenv("SENTRY_DSN", "https://fake@sentry.invalid/1")
    from src.artiscrapper import config as cfg
    importlib.reload(cfg)
    from src.artiscrapper import logging_setup
    importlib.reload(logging_setup)

    # Push a correlation_id into the asgi-correlation-id contextvar.
    from asgi_correlation_id.context import correlation_id

    token = correlation_id.set("test-cid-xyz-123")
    try:
        # Run the structlog processor manually with an empty event dict.
        out = logging_setup.add_correlation_id(None, "info", {})
        assert out.get("correlation_id") == "test-cid-xyz-123", (
            f"add_correlation_id must inject correlation_id into event_dict; got {out!r}"
        )
        # And read the tag back off the Sentry scope (D-16).
        scope = sentry_sdk.get_current_scope()
        # In sentry-sdk 2.x the scope stores tags under the private `_tags` dict;
        # set_tag() is the public writer. Read either via the dict directly or
        # via the publicly documented `get_tag` path if available.
        tag_value = getattr(scope, "_tags", {}).get("correlation_id")
        assert tag_value == "test-cid-xyz-123", (
            f"D-16: tags.correlation_id must equal the contextvar value; got {tag_value!r}"
        )
    finally:
        correlation_id.reset(token)


@pytest.mark.parametrize("dsn,expected_event", [
    ("", "sentry_init_skipped"),
    ("https://fake@sentry.invalid/1", "sentry_init_done"),
])
def test_lifespan_log_matches_sdk_state(monkeypatch, caplog, dsn, expected_event):
    """
    WRN-04 (D-19): the lifespan emits exactly one of
    `sentry_init_done` / `sentry_init_skipped`; the event name MUST match
    sentry_sdk.get_client().is_active() — they cannot diverge.

    Implementation note: structlog.testing.capture_logs() does NOT survive
    `configure_logging()` reconfiguring the processor chain inside lifespan
    (the new processor chain is built from scratch). We instead drive
    structlog through stdlib logging (LoggerFactory) and use pytest's
    `caplog` fixture which hooks the stdlib root logger at the propagate
    level — capturing the JSON-rendered messages.
    """
    import logging as _logging

    monkeypatch.setenv("SENTRY_DSN", dsn)
    monkeypatch.setenv("API_KEYS", "test-key-1")
    # Reload modules so SDK init runs under the new env.
    from src.artiscrapper import config as cfg
    importlib.reload(cfg)
    from src.artiscrapper import logging_setup
    importlib.reload(logging_setup)
    from src.artiscrapper import main as main_mod
    importlib.reload(main_mod)

    # TestClient is imported lazily so the reloaded app object is used.
    from fastapi.testclient import TestClient

    mock_browser = _make_mock_browser()

    async def _fake_launch_async(**kwargs):
        return mock_browser

    monkeypatch.setattr(main_mod, "launch_async", _fake_launch_async)

    caplog.set_level(_logging.INFO)
    with TestClient(main_mod.app):
        pass  # boot + shutdown — enough to emit lifespan logs

    # JSON-rendered structlog events flow through stdlib logging; caplog.text
    # concatenates all captured records (level + logger + message). We grep
    # for the event key serialized into the JSON.
    sentry_lines = [
        msg for msg in caplog.messages
        if "sentry_init_done" in msg or "sentry_init_skipped" in msg
    ]
    assert len(sentry_lines) >= 1, (
        f"WRN-04: lifespan must emit a sentry_init_* log; "
        f"captured messages were:\n  " + "\n  ".join(caplog.messages[:30])
    )
    actual_event = (
        "sentry_init_done" if "sentry_init_done" in sentry_lines[-1]
        else "sentry_init_skipped"
    )
    assert actual_event == expected_event, (
        f"WRN-04: expected event {expected_event!r} for DSN={dsn!r}; "
        f"got {actual_event!r} on line: {sentry_lines[-1]}"
    )
    # Cross-check the SDK state against the log event name.
    is_active = sentry_sdk.get_client().is_active()
    if actual_event == "sentry_init_done":
        assert is_active is True, (
            "WRN-04: log says done but get_client().is_active() is False"
        )
    else:
        assert is_active is False, (
            "WRN-04: log says skipped but get_client().is_active() is True"
        )
