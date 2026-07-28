"""Regression tests for WhatsApp pairing event delivery.

The bug these pin: pairing silently hung forever.

Every Socket.IO emit in whatsapp_bot_service fires from a background worker
thread (WhatsAppPairThread / WhatsAppBotThread) where there is no Flask
request context. When per-user emit scoping was introduced, `_emit` resolved
its recipient from the Flask session, falling back to the persisted
`owner_username`. During pairing BOTH are empty -- the worker has no session,
and `owner_username` is only written by save_session_blob() at the END of a
successful pair. So the QR code and pair code were dropped, the UI had
nothing to render, and pairing could never complete. Because pairing never
completed, `owner_username` was never persisted, so every slash command then
failed with "No owner recorded for this paired device".

The fix captures the owner on the REQUEST thread in start_pair() and holds it
on the instance for the worker threads to use.
"""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from flask import Flask  # noqa: E402

import extensions  # noqa: E402
import services.whatsapp_bot_service as wa_service  # noqa: E402
from services.whatsapp_bot_service import whatsapp_bot_service as svc  # noqa: E402


class FakeSocketIO:
    def __init__(self):
        self.emitted = []

    def emit(self, event, payload=None, *args, **kwargs):
        self.emitted.append((event, payload, kwargs.get("room")))


@pytest.fixture
def fake_socketio(monkeypatch):
    fake = FakeSocketIO()
    monkeypatch.setattr(extensions, "socketio", fake)
    return fake


@pytest.fixture(autouse=True)
def _reset_owner():
    original = svc._owner_username
    svc._owner_username = None
    yield
    svc._owner_username = original


def _emit_on_worker_thread(event, payload):
    """Run svc._emit exactly as pairing does: on a plain worker thread with
    no Flask request context."""
    err = {}

    def worker():
        try:
            svc._emit(event, payload)
        except Exception as e:  # pragma: no cover - surfaced via assert below
            err["e"] = e

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert "e" not in err, f"_emit raised on worker thread: {err.get('e')}"


# ---------------------------------------------------------------------
# The core regression
# ---------------------------------------------------------------------


def test_qr_reaches_owner_from_worker_thread(fake_socketio, monkeypatch):
    """THE regression test: the QR must be delivered from a worker thread,
    scoped to the admin who started pairing."""
    monkeypatch.setattr(wa_service, "get_bot_config", lambda: {})
    svc._owner_username = "alice"  # as start_pair() captures it

    _emit_on_worker_thread("whatsapp_qr", {"data_url": "data:image/png;base64,AAA"})

    assert fake_socketio.emitted == [
        ("whatsapp_qr", {"data_url": "data:image/png;base64,AAA"}, "user_alice")
    ]


def test_pair_code_reaches_owner_from_worker_thread(fake_socketio, monkeypatch):
    monkeypatch.setattr(wa_service, "get_bot_config", lambda: {})
    svc._owner_username = "alice"

    _emit_on_worker_thread("whatsapp_pair_code", {"code": "ABCD-1234"})

    assert fake_socketio.emitted[0][2] == "user_alice"


def test_pairing_event_is_never_silently_dropped(fake_socketio, monkeypatch):
    """Even with NO resolvable owner the QR must still reach the browser.

    A dropped QR makes pairing impossible and looks like a hang; broadcasting
    a short-lived, operator-initiated pairing code is the lesser evil. This
    is the property whose absence caused the reported bug.
    """
    monkeypatch.setattr(wa_service, "get_bot_config", lambda: {})
    svc._owner_username = None

    _emit_on_worker_thread("whatsapp_qr", {"data_url": "x"})

    assert len(fake_socketio.emitted) == 1, "the QR must not be dropped"
    assert fake_socketio.emitted[0][2] is None, "unscoped fallback broadcast"


# ---------------------------------------------------------------------
# Owner resolution order
# ---------------------------------------------------------------------


def test_falls_back_to_persisted_owner_after_restart(fake_socketio, monkeypatch):
    """After a process restart the bot thread runs without ever having
    called start_pair(), so the owner comes from the DB."""
    monkeypatch.setattr(wa_service, "get_bot_config", lambda: {"owner_username": "bob"})
    svc._owner_username = None

    _emit_on_worker_thread("whatsapp_status", {"is_running": True})

    assert fake_socketio.emitted[0][2] == "user_bob"


def test_captured_owner_wins_over_persisted(fake_socketio, monkeypatch):
    """The in-flight pairing admin takes precedence over a stale DB row --
    otherwise re-pairing sends the new QR to the previous owner."""
    monkeypatch.setattr(wa_service, "get_bot_config", lambda: {"owner_username": "old"})
    svc._owner_username = "new"

    _emit_on_worker_thread("whatsapp_qr", {"data_url": "x"})

    assert fake_socketio.emitted[0][2] == "user_new"


def test_session_used_when_on_request_thread(fake_socketio, monkeypatch):
    """Emits that DO happen on a request thread (e.g. stop_bot from the UI)
    still resolve correctly."""
    monkeypatch.setattr(wa_service, "get_bot_config", lambda: {})
    svc._owner_username = None

    app = Flask(__name__)
    app.secret_key = "test-secret"
    with app.test_request_context("/"):
        from flask import session as flask_session

        flask_session["user"] = "carol"
        svc._emit("whatsapp_status", {"is_running": False})

    assert fake_socketio.emitted[0][2] == "user_carol"


def test_session_lookup_is_safe_off_request_thread():
    """_session_username must return None rather than raising when called
    from a worker thread -- the whole fallback chain depends on it."""
    result = {}

    def worker():
        result["v"] = wa_service._session_username()

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    assert result["v"] is None


def test_config_lookup_failure_does_not_break_emit(fake_socketio, monkeypatch):
    """A DB error while resolving the owner must not stop the QR being
    delivered."""
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(wa_service, "get_bot_config", boom)
    svc._owner_username = None

    _emit_on_worker_thread("whatsapp_qr", {"data_url": "x"})

    assert len(fake_socketio.emitted) == 1


# ---------------------------------------------------------------------
# Owner lifecycle
# ---------------------------------------------------------------------


def test_unlink_clears_cached_owner(fake_socketio, monkeypatch):
    """After unlink, a re-pair by a DIFFERENT admin must not route their QR
    to the previous owner."""
    monkeypatch.setattr(wa_service, "get_bot_config", lambda: {})
    monkeypatch.setattr(wa_service, "clear_session_blob", lambda: True)
    monkeypatch.setattr(svc, "stop_bot", lambda: (True, "stopped"))

    svc._owner_username = "alice"
    ok, _msg = svc.unlink()

    assert ok is True
    assert svc._owner_username is None, "stale owner must not survive unlink"
    # The unlink notification itself still went to alice, who performed it.
    assert fake_socketio.emitted[0][2] == "user_alice"
