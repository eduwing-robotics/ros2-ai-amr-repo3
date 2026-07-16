"""Callback adapter SSRF/confused-deputy regressions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nav_app.adapters import callbacks


def _configured_main_base() -> str:
    return "https://main.example/api/v1"


def test_rejects_command_supplied_internal_callback_endpoint():
    with patch.object(callbacks, "MAIN_API_BASE", _configured_main_base()), patch.object(callbacks, "MAIN_CALLBACK_HMAC_SECRET", "secret"), patch(
        "nav_app.adapters.callbacks.request.build_opener"
    ) as opener:
        assert not callbacks.post_json_callback("http://127.0.0.1:2375/containers/json", {"event": "DONE"})
    opener.assert_not_called()


def test_rejects_private_ipv6_and_dns_private_callback_destinations():
    with patch.object(callbacks, "MAIN_API_BASE", _configured_main_base()), patch.object(callbacks, "MAIN_CALLBACK_HMAC_SECRET", "secret"), patch(
        "nav_app.adapters.callbacks.request.build_opener"
    ) as opener:
        assert not callbacks.post_json_callback("https://[::1]/api/v1/movement/command-events", {})
    opener.assert_not_called()

    with patch.object(callbacks, "MAIN_API_BASE", _configured_main_base()), patch.object(callbacks, "MAIN_CALLBACK_HMAC_SECRET", "secret"), patch(
        "nav_app.adapters.callbacks.socket.getaddrinfo", return_value=[(0, 0, 0, "", ("192.168.1.2", 443))]
    ), patch("nav_app.adapters.callbacks.request.build_opener") as opener:
        assert not callbacks.post_json_callback("https://main.example/api/v1/movement/command-events", {})
    opener.assert_not_called()


def test_valid_configured_callback_is_canonical_hmac_signed_and_does_not_follow_redirects():
    response = MagicMock(status=204)
    response.__enter__.return_value = response
    with patch.object(callbacks, "MAIN_API_BASE", "https://MAIN.example:443/api/v1/"), patch.object(
        callbacks, "MAIN_CALLBACK_HMAC_SECRET", "secret"
    ), patch("nav_app.adapters.callbacks.socket.getaddrinfo", return_value=[(0, 0, 0, "", ("8.8.8.8", 443))]), patch(
        "nav_app.adapters.callbacks.request.build_opener"
    ) as build_opener, patch("nav_app.adapters.callbacks.sign_headers", return_value={"X-Signature": "signed"}) as sign:
        build_opener.return_value.open.return_value = response
        assert callbacks.post_json_callback("https://main.example/api/v1/movement/command-events", {"event": "DONE"})

    signed_url = sign.call_args.args[2]
    assert signed_url == "https://main.example/api/v1/movement/command-events"
    assert build_opener.return_value.open.call_args.kwargs["timeout"] == callbacks.CALLBACK_TIMEOUT_SEC
    assert isinstance(build_opener.return_value.open.call_args.args[0], callbacks.request.Request)
    assert build_opener.call_args.args[0].__class__.__name__ == "_NoRedirect"


def test_redirect_response_is_not_followed_or_accepted():
    redirect = MagicMock(status=302)
    redirect.__enter__.return_value = redirect
    with patch.object(callbacks, "MAIN_API_BASE", _configured_main_base()), patch.object(callbacks, "MAIN_CALLBACK_HMAC_SECRET", "secret"), patch(
        "nav_app.adapters.callbacks.socket.getaddrinfo", return_value=[(0, 0, 0, "", ("8.8.8.8", 443))]
    ), patch("nav_app.adapters.callbacks.request.build_opener") as build_opener:
        build_opener.return_value.open.return_value = redirect
        assert not callbacks.post_main_callback("/movement/command-events", {})
    assert build_opener.return_value.open.call_count == 1


def test_nohardware_explicit_localhost_allowlist_allows_only_configured_main_endpoint(monkeypatch):
    monkeypatch.setenv("NAV_NOHARDWARE", "1")
    monkeypatch.setenv("NAV_NOHARDWARE_CALLBACK_ALLOWLIST", "http://localhost:8088")
    response = MagicMock(status=204)
    response.__enter__.return_value = response
    with patch.object(callbacks, "MAIN_API_BASE", "http://localhost:8088/api/v1"), patch.object(
        callbacks, "MAIN_CALLBACK_HMAC_SECRET", "secret"
    ), patch("nav_app.adapters.callbacks.request.build_opener") as build_opener:
        build_opener.return_value.open.return_value = response
        assert callbacks.post_main_callback("/movement/command-events", {})
        assert not callbacks.post_json_callback("http://localhost:8088/api/v1/other", {})


def test_physical_field_lan_callback_requires_exact_explicit_allowlist(monkeypatch):
    monkeypatch.delenv("NAV_NOHARDWARE", raising=False)
    monkeypatch.setenv("NAV_MAIN_CALLBACK_ALLOWLIST", "http://192.168.30.5:8088")
    response = MagicMock(status=204)
    response.__enter__.return_value = response
    with patch.object(callbacks, "MAIN_API_BASE", "http://192.168.30.5:8088/api/v1"), patch.object(
        callbacks, "MAIN_CALLBACK_HMAC_SECRET", "secret"
    ), patch("nav_app.adapters.callbacks.request.build_opener") as build_opener:
        build_opener.return_value.open.return_value = response
        assert callbacks.post_main_callback("/movement/command-events", {})

    monkeypatch.delenv("NAV_MAIN_CALLBACK_ALLOWLIST")
    with patch.object(callbacks, "MAIN_API_BASE", "http://192.168.30.5:8088/api/v1"), patch.object(
        callbacks, "MAIN_CALLBACK_HMAC_SECRET", "secret"
    ):
        assert not callbacks.post_main_callback("/movement/command-events", {})
