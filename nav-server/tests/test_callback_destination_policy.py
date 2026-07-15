"""Callback adapter trusted-site/SSRF regressions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nav_app.adapters import callbacks


def _configured_main_base() -> str:
    return "http://smartfactory-main.local:8088/api/v1"


def _site_dns(address: str = "192.168.30.5"):
    return patch(
        "nav_app.adapters.callbacks.socket.getaddrinfo",
        return_value=[(0, 0, 0, "", (address, 8088))],
    )


def test_rejects_command_supplied_or_noncanonical_callback_endpoint():
    with (
        patch.object(callbacks, "MAIN_API_BASE", _configured_main_base()),
        patch.object(callbacks, "MAIN_CALLBACK_HMAC_SECRET", "secret"),
        patch("nav_app.adapters.callbacks.request.build_opener") as opener,
    ):
        assert not callbacks.post_json_callback(
            "http://127.0.0.1:2375/containers/json", {"event": "DONE"}
        )
        assert not callbacks.post_json_callback(
            "http://smartfactory-main.local:8088/api/v1/other", {}
        )
        assert not callbacks.post_json_callback(
            "http://user@smartfactory-main.local:8088/api/v1/movement/command-events", {}
        )
        assert not callbacks.post_json_callback(
            "http://smartfactory-main.local:8088/api/v1/movement/command-events?x=1", {}
        )
    opener.assert_not_called()


@pytest.mark.parametrize("resolved", ["10.0.0.8", "192.168.10.9", "8.8.8.8"])
def test_rejects_dns_outside_commissioned_site_network(resolved):
    with (
        patch.object(callbacks, "MAIN_API_BASE", _configured_main_base()),
        patch.object(callbacks, "MAIN_CALLBACK_HMAC_SECRET", "secret"),
        _site_dns(resolved),
        patch("nav_app.adapters.callbacks.request.build_opener") as opener,
    ):
        assert not callbacks.post_main_callback("/movement/command-events", {})
    opener.assert_not_called()


def test_rejects_direct_ip_identity_even_inside_site_network():
    with (
        patch.object(callbacks, "MAIN_API_BASE", "http://192.168.30.5:8088/api/v1"),
        patch.object(callbacks, "MAIN_CALLBACK_HMAC_SECRET", "secret"),
        patch("nav_app.adapters.callbacks.request.build_opener") as opener,
    ):
        assert not callbacks.post_main_callback("/movement/command-events", {})
    opener.assert_not_called()


def test_valid_site_callback_is_canonical_hmac_signed_and_does_not_follow_redirects():
    response = MagicMock(status=204)
    response.__enter__.return_value = response
    with (
        patch.object(
            callbacks,
            "MAIN_API_BASE",
            "http://SMARTFACTORY-MAIN.local:8088/api/v1/",
        ),
        patch.object(callbacks, "MAIN_CALLBACK_HMAC_SECRET", "secret"),
        _site_dns(),
        patch("nav_app.adapters.callbacks.request.build_opener") as build_opener,
        patch(
            "nav_app.adapters.callbacks.sign_headers",
            return_value={"X-Signature": "signed"},
        ) as sign,
    ):
        build_opener.return_value.open.return_value = response
        assert callbacks.post_json_callback(
            "http://smartfactory-main.local:8088/api/v1/movement/command-events",
            {"event": "DONE"},
        )

    signed_url = sign.call_args.args[2]
    assert signed_url == (
        "http://smartfactory-main.local:8088/api/v1/movement/command-events"
    )
    assert (
        build_opener.return_value.open.call_args.kwargs["timeout"]
        == callbacks.CALLBACK_TIMEOUT_SEC
    )
    assert isinstance(
        build_opener.return_value.open.call_args.args[0], callbacks.request.Request
    )
    assert build_opener.call_args.args[0].__class__.__name__ == "_NoRedirect"


def test_redirect_response_is_not_followed_or_accepted():
    redirect = MagicMock(status=302)
    redirect.__enter__.return_value = redirect
    with (
        patch.object(callbacks, "MAIN_API_BASE", _configured_main_base()),
        patch.object(callbacks, "MAIN_CALLBACK_HMAC_SECRET", "secret"),
        _site_dns(),
        patch("nav_app.adapters.callbacks.request.build_opener") as build_opener,
    ):
        build_opener.return_value.open.return_value = redirect
        assert not callbacks.post_main_callback("/movement/command-events", {})
    assert build_opener.return_value.open.call_count == 1


def test_nohardware_explicit_localhost_allowlist_allows_only_configured_main_endpoint(
    monkeypatch,
):
    monkeypatch.setenv("NAV_NOHARDWARE", "1")
    monkeypatch.setenv("NAV_NOHARDWARE_CALLBACK_ALLOWLIST", "http://localhost:8088")
    response = MagicMock(status=204)
    response.__enter__.return_value = response
    with (
        patch.object(callbacks, "MAIN_API_BASE", "http://localhost:8088/api/v1"),
        patch.object(callbacks, "MAIN_CALLBACK_HMAC_SECRET", "secret"),
        patch("nav_app.adapters.callbacks.request.build_opener") as build_opener,
    ):
        build_opener.return_value.open.return_value = response
        assert callbacks.post_main_callback("/movement/command-events", {})
        assert not callbacks.post_json_callback(
            "http://localhost:8088/api/v1/other", {}
        )
