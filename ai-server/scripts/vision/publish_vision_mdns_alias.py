#!/usr/bin/env python3
"""Temporarily publish smartfactory-vision.local via Avahi/mDNS.

This is a no-root, foreground helper for local integration tests. It publishes an
A record only; it does not change hostname, /etc/hosts, router DHCP, or DNS.
For production, prefer router DHCP reservation plus DNS/mDNS hostname setup.
"""

from __future__ import annotations

import argparse
import ipaddress
import signal
import socket
import subprocess
from typing import Sequence

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

AVAHI_IF_UNSPEC = -1
AVAHI_PROTO_INET = 0
AVAHI_PUBLISH_UNIQUE = 0
DNS_CLASS_IN = 1
DNS_TYPE_A = 1
DEFAULT_TTL_SECONDS = 120
DEFAULT_NAME = "smartfactory-vision.local"


def _default_lan_ip() -> str:
    """Return the first non-loopback IPv4 from hostname -I."""

    try:
        output = subprocess.check_output(["hostname", "-I"], text=True, timeout=2)
    except Exception as exc:  # noqa: BLE001 - CLI should report environment failures simply
        raise SystemExit(f"failed to detect LAN IP with hostname -I: {exc}") from exc
    for token in output.split():
        try:
            address = ipaddress.ip_address(token)
        except ValueError:
            continue
        if address.version == 4 and not address.is_loopback:
            return str(address)
    raise SystemExit("no non-loopback IPv4 address found; pass --address explicitly")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Publish a temporary Avahi/mDNS A record for smartfactory-vision.local. "
            "Run in foreground; Ctrl-C withdraws the record."
        )
    )
    parser.add_argument(
        "--name", default=DEFAULT_NAME, help=f"mDNS name to publish (default: {DEFAULT_NAME})"
    )
    parser.add_argument(
        "--address", default=None, help="IPv4 address to publish; defaults to first LAN IPv4"
    )
    parser.add_argument("--ttl", type=int, default=DEFAULT_TTL_SECONDS, help="DNS TTL seconds")
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print the resolved name/address that would be published, then exit without touching Avahi",
    )
    return parser


def publish_record(*, name: str, address: str, ttl: int) -> int:
    if not name.endswith(".local"):
        raise SystemExit("--name must end with .local for mDNS")
    packed = socket.inet_aton(address)

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    server = dbus.Interface(
        bus.get_object("org.freedesktop.Avahi", "/"), "org.freedesktop.Avahi.Server"
    )
    path = server.EntryGroupNew()
    group = dbus.Interface(
        bus.get_object("org.freedesktop.Avahi", path), "org.freedesktop.Avahi.EntryGroup"
    )
    rdata = dbus.Array([dbus.Byte(byte) for byte in packed], signature="y")
    group.AddRecord(
        dbus.Int32(AVAHI_IF_UNSPEC),
        dbus.Int32(AVAHI_PROTO_INET),
        dbus.UInt32(AVAHI_PUBLISH_UNIQUE),
        name,
        dbus.UInt16(DNS_CLASS_IN),
        dbus.UInt16(DNS_TYPE_A),
        dbus.UInt32(ttl),
        rdata,
    )
    group.Commit()
    print(f"published A {name} -> {address} via Avahi D-Bus group={path}", flush=True)
    print(
        "temporary record is active while this process is running; press Ctrl-C to stop", flush=True
    )

    loop = GLib.MainLoop()

    def stop(*_: object) -> None:
        try:
            group.Reset()
            print(f"withdrew A {name}", flush=True)
        finally:
            loop.quit()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    loop.run()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    address = args.address or _default_lan_ip()
    try:
        ipaddress.IPv4Address(address)
    except ValueError as exc:
        raise SystemExit(f"--address must be IPv4: {address}") from exc
    if args.ttl <= 0:
        raise SystemExit("--ttl must be positive")
    if args.print_only:
        print(f"would publish A {args.name} -> {address} ttl={args.ttl}")
        return 0
    return publish_record(name=args.name, address=address, ttl=args.ttl)


if __name__ == "__main__":
    raise SystemExit(main())
