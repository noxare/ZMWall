from zmwall.diagnostics import probe_command, redact


def test_diagnostic_output_redacts_url_and_credentials():
    url = "rtsp://server/75?username=admin&password=s3cret"
    output = f"Playing {url}\nusername=admin password=s3cret\n"
    safe = redact(output, url, "admin", "s3cret")
    assert url not in safe
    assert "admin" not in safe
    assert "s3cret" not in safe
    assert "<RTSP-URL>" in safe


def test_forced_profile_probe_only_disables_profile_check_for_diagnostic():
    assert "--vd-lavc-check-hw-profile=no" not in probe_command()
    assert "--vd-lavc-check-hw-profile=no" in probe_command(ignore_profile_check=True)
    assert "--hwdec-software-fallback=no" in probe_command(ignore_profile_check=True)
