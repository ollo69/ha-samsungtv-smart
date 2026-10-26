"""TLS pairing waits for Allow instead of failing the first auth event."""

import base64
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


def _load_samsungws():
    """Load the websocket module without the integration package init."""
    root = Path(__file__).resolve().parents[1]
    pkg = "custom_components"
    comp = "custom_components.samsungtv_smart"
    api = "custom_components.samsungtv_smart.api"
    shortcuts_name = api + ".shortcuts"
    for name in (pkg, comp, api):
        sys.modules.setdefault(name, types.ModuleType(name))
    shortcuts = types.ModuleType(shortcuts_name)

    class SamsungTVShortcuts:
        """Stand-in so the websocket module can import."""

    shortcuts.SamsungTVShortcuts = SamsungTVShortcuts
    sys.modules[shortcuts_name] = shortcuts
    spec = importlib.util.spec_from_file_location(
        api + ".samsungws",
        root / "custom_components/samsungtv_smart/api/samsungws.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


samsungws = _load_samsungws()


class _FakeSocket:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []
        self.closed = False

    def send(self, payload):
        self.sent.append(payload)

    def recv(self):
        if not self.messages:
            raise TimeoutError("no more frames")
        return self.messages.pop(0)

    def close(self):
        self.closed = True


def _connect_event(name, token):
    device_name = base64.b64encode(name.encode()).decode()
    return json.dumps(
        {
            "event": "ms.channel.connect",
            "data": {
                "id": "client-1",
                "token": token,
                "clients": [{"id": "client-1", "deviceName": device_name}],
            },
        }
    )


def test_tls_open_waits_past_no_authorized(monkeypatch):
    """Port 8002 sends a register frame and keeps the token from the later connect."""
    sock = _FakeSocket(
        [
            json.dumps({"event": "ms.error", "data": {"message": "No Authorized"}}),
            _connect_event("Frame", "fresh-token"),
        ]
    )

    def _create(url, timeout, sslopt):
        assert url.startswith("wss://tv:8002/")
        assert "cert_reqs" in sslopt
        assert timeout == 5
        return sock

    monkeypatch.setattr(samsungws.websocket, "create_connection", _create)
    remote = samsungws.SamsungTVWS(host="tv", port=8002, name="Frame", timeout=5)
    remote.open()

    assert remote.token == "fresh-token"
    sent = json.loads(sock.sent[0])
    assert sent["method"] == "ms.channel.connect"
    assert sent["params"]["deviceName"] == "Frame"
    assert sent["params"]["token"] == ""
    assert sock.closed is False


def test_plain_open_still_fails_on_unauthorized(monkeypatch):
    """Port 8001 must not wait. The server closes that socket."""
    sock = _FakeSocket([json.dumps({"event": "ms.channel.unauthorized"})])

    def _create(url, timeout, sslopt):
        assert url.startswith("ws://tv:8001/")
        assert sslopt == {}
        return sock

    monkeypatch.setattr(samsungws.websocket, "create_connection", _create)
    remote = samsungws.SamsungTVWS(host="tv", port=8001, name="Frame", timeout=5)
    with pytest.raises(samsungws.ConnectionFailure):
        remote.open()
    assert sock.sent == []
    assert sock.closed is True
