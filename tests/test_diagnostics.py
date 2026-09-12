from zmwall.diagnostics import redact


def test_diagnostic_output_redacts_url_and_credentials():
    url = "rtsp://server/75?username=admin&password=s3cret"
    output = f"Playing {url}\nusername=admin password=s3cret\n"
    safe = redact(output, url, "admin", "s3cret")
    assert url not in safe
    assert "admin" not in safe
    assert "s3cret" not in safe
    assert "<RTSP-URL>" in safe
