from zmwall import network


def test_detects_concurrent_lan_and_wifi_connections(monkeypatch):
    monkeypatch.setattr(network, "_default_routes", lambda: {"enp1s0": "192.168.1.1"})
    monkeypatch.setattr(network, "_address_data", lambda: [
        {
            "ifname": "wlp2s0", "addr_info": [
                {"family": "inet", "scope": "global", "local": "192.168.1.23", "prefixlen": 24},
            ],
        },
        {
            "ifname": "enp1s0", "addr_info": [
                {"family": "inet", "scope": "global", "local": "192.168.1.24", "prefixlen": 24},
            ],
        },
    ])
    monkeypatch.setattr(network, "_is_physical", lambda _interface: True)
    monkeypatch.setattr(network, "_interface_kind", lambda interface: "wifi" if interface.startswith("wl") else "ethernet")
    monkeypatch.setattr(network, "_speed", lambda interface: "1000 Mbit/s" if interface == "enp1s0" else None)
    monkeypatch.setattr(
        network, "_wifi_link",
        lambda _interface: {"ssid": "Camera-Net", "signal": "-48 dBm", "bitrate": "433.3 MBit/s"},
    )

    status = network.detect_network_status()

    assert status["state"] == "connected"
    assert [item["interface"] for item in status["connections"]] == ["enp1s0", "wlp2s0"]
    assert status["connections"][0]["default"] is True
    assert status["connections"][1]["ssid"] == "Camera-Net"


def test_ignores_virtual_non_routed_interfaces(monkeypatch):
    monkeypatch.setattr(network, "_default_routes", lambda: {})
    monkeypatch.setattr(network, "_address_data", lambda: [
        {
            "ifname": "docker0", "addr_info": [
                {"family": "inet", "scope": "global", "local": "172.17.0.1", "prefixlen": 16},
            ],
        },
    ])
    monkeypatch.setattr(network, "_is_physical", lambda _interface: False)

    assert network.detect_network_status() == {"state": "offline", "connections": []}


def test_diagnostic_lines_include_link_details():
    lines = network.diagnostic_lines({
        "state": "connected",
        "connections": [{
            "type": "wifi", "interface": "wlp2s0", "ipv4": "192.168.1.23",
            "prefix_length": 24, "gateway": "192.168.1.1", "default": True,
            "speed": None, "ssid": "Camera-Net", "signal": "-48 dBm",
            "bitrate": "433.3 MBit/s",
        }],
    })

    report = "\n".join(lines)
    assert "WLAN wlp2s0: 192.168.1.23/24" in report
    assert "SSID Camera-Net" in report
    assert "Gateway 192.168.1.1" in report
    assert "Standardroute" in report
