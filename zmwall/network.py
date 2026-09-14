"""Read-only detection of active physical LAN and Wi-Fi connections."""

from __future__ import annotations

import json
import re
import socket
import struct
import subprocess
import fcntl
from pathlib import Path
from typing import Any


SYS_CLASS_NET = Path("/sys/class/net")
PROC_NET_ROUTE = Path("/proc/net/route")


def _address_data() -> list[dict[str, Any]]:
    try:
        result = subprocess.run(
            ["ip", "-j", "address", "show", "up"],
            check=False, capture_output=True, text=True, timeout=2,
        )
        data = json.loads(result.stdout) if result.returncode == 0 else []
        if isinstance(data, list) and data:
            return data
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        pass
    return _fallback_address_data()


def _fallback_address_data() -> list[dict[str, Any]]:
    """Read IPv4 addresses through Linux ioctls when iproute2 is unavailable."""
    data: list[dict[str, Any]] = []
    try:
        interfaces = socket.if_nameindex()
    except OSError:
        return data
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        for _index, interface in interfaces:
            request = struct.pack("256s", interface[:15].encode())
            try:
                address = socket.inet_ntoa(fcntl.ioctl(client.fileno(), 0x8915, request)[20:24])
                netmask = socket.inet_ntoa(fcntl.ioctl(client.fileno(), 0x891B, request)[20:24])
            except OSError:
                continue
            prefix_length = sum(bin(int(octet)).count("1") for octet in netmask.split("."))
            data.append({
                "ifname": interface,
                "addr_info": [{
                    "family": "inet", "scope": "global",
                    "local": address, "prefixlen": prefix_length,
                }],
            })
    return data


def _default_routes() -> dict[str, str | None]:
    """Map interfaces with an IPv4 default route to their gateway."""
    routes: dict[str, str | None] = {}
    try:
        lines = PROC_NET_ROUTE.read_text(errors="replace").splitlines()[1:]
    except OSError:
        return routes
    for line in lines:
        fields = line.split()
        if len(fields) < 4 or fields[1] != "00000000":
            continue
        try:
            flags = int(fields[3], 16)
            gateway_hex = fields[2]
            gateway = ".".join(str(int(gateway_hex[index:index + 2], 16)) for index in (6, 4, 2, 0))
        except ValueError:
            continue
        if flags & 0x1:
            routes[fields[0]] = gateway if gateway != "0.0.0.0" else None
    return routes


def _interface_kind(interface: str) -> str:
    return "wifi" if (SYS_CLASS_NET / interface / "wireless").exists() or interface.startswith("wl") else "ethernet"


def _is_physical(interface: str) -> bool:
    path = SYS_CLASS_NET / interface
    return (path / "device").exists() or (path / "wireless").exists()


def _speed(interface: str) -> str | None:
    try:
        value = int((SYS_CLASS_NET / interface / "speed").read_text().strip())
    except (OSError, ValueError):
        return None
    return f"{value} Mbit/s" if value > 0 else None


def _wifi_link(interface: str) -> dict[str, str]:
    try:
        result = subprocess.run(
            ["iw", "dev", interface, "link"],
            check=False, capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode:
        return {}
    details: dict[str, str] = {}
    patterns = {
        "ssid": r"^\s*SSID:\s*(.+)$",
        "signal": r"^\s*signal:\s*(.+)$",
        "bitrate": r"^\s*tx bitrate:\s*(.+)$",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, result.stdout, flags=re.MULTILINE)
        if match:
            details[key] = match.group(1).strip()
    return details


def detect_network_status() -> dict[str, Any]:
    """Return active physical interfaces, including concurrent LAN and Wi-Fi."""
    routes = _default_routes()
    connections: list[dict[str, Any]] = []
    for item in _address_data():
        interface = str(item.get("ifname", ""))
        if not interface or interface == "lo":
            continue
        addresses = [
            address for address in item.get("addr_info", [])
            if address.get("family") == "inet" and address.get("scope") == "global"
        ]
        if not addresses or (not _is_physical(interface) and interface not in routes):
            continue
        address = addresses[0]
        kind = _interface_kind(interface)
        connection: dict[str, Any] = {
            "type": kind,
            "interface": interface,
            "ipv4": str(address.get("local", "")),
            "prefix_length": address.get("prefixlen"),
            "default": interface in routes,
            "gateway": routes.get(interface),
            "speed": _speed(interface),
        }
        if kind == "wifi":
            connection.update(_wifi_link(interface))
        connections.append(connection)
    connections.sort(key=lambda value: (not value["default"], value["type"] != "ethernet", value["interface"]))
    return {"state": "connected" if connections else "offline", "connections": connections}


def diagnostic_lines(status: dict[str, Any] | None = None) -> list[str]:
    """Format network information for the existing German diagnostic report."""
    current = status if status is not None else detect_network_status()
    lines = ["Netzwerk:"]
    connections = current.get("connections", [])
    if not connections:
        return [*lines, "  Keine aktive LAN-/WLAN-Verbindung erkannt"]
    for connection in connections:
        label = "WLAN" if connection.get("type") == "wifi" else "LAN"
        ip = connection.get("ipv4") or "keine IPv4-Adresse"
        prefix = connection.get("prefix_length")
        if prefix is not None and connection.get("ipv4"):
            ip = f"{ip}/{prefix}"
        details = [f"{label} {connection.get('interface', '?')}: {ip}"]
        if connection.get("ssid"):
            details.append(f"SSID {connection['ssid']}")
        if connection.get("gateway"):
            details.append(f"Gateway {connection['gateway']}")
        if connection.get("speed"):
            details.append(str(connection["speed"]))
        if connection.get("signal"):
            details.append(f"Signal {connection['signal']}")
        if connection.get("bitrate"):
            details.append(f"TX {connection['bitrate']}")
        if connection.get("default"):
            details.append("Standardroute")
        lines.append("  - " + " · ".join(details))
    return lines
