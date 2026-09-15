from zmwall import diagnostics
from zmwall.diagnostics import probe_command, probe_stream_summary, redact, summary_probe_command


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


def test_summary_probe_reads_one_frame_without_testing_gpu_capacity():
    command = summary_probe_command()
    assert "--frames=1" in command
    assert "--hwdec=no" in command
    assert not any(option.startswith("--hwdec=auto") for option in command)


def test_summary_probe_detects_resolution_without_inferring_gpu_limit(monkeypatch):
    class Process:
        returncode = 0

        def communicate(self, _input=None, timeout=None):
            return (
                "[vd] Selected decoder: h264 - H.264\n"
                "[vd] Codec profile: High (0x64)\n"
                "[vd] Container reported FPS: 15.000000\n"
                "[ffmpeg/video] h264: Hardware does not support image size 3840x2160.\n"
                "[ffmpeg/video] h264: Reinit context to 3840x2160, pix_fmt: yuvj420p\n",
                None,
            )

    monkeypatch.setattr(diagnostics, "render_rtsp", lambda row, _camera: "rtsp://secret")
    monkeypatch.setattr(diagnostics.subprocess, "Popen", lambda *args, **kwargs: Process())
    result = probe_stream_summary({
        "camera_key": "1:63", "username": "admin", "password": "secret",
    })
    assert result["actual_width"] == 3840
    assert result["actual_height"] == 2160
    assert result["codec"] == "h264"
    assert result["profile"] == "High"
    assert result["fps"] == "15.000000"
    assert result["gpu_compatible"] is None
    assert result["status"] == "ok"


def test_summary_probe_does_not_mix_old_hardware_messages_into_resolution(monkeypatch):
    class Process:
        returncode = 0

        def communicate(self, _input=None, timeout=None):
            return (
                "[ffmpeg/video] h264: Hardware does not support image size 720x576.\n"
                "[vd] Attempting next decoding method after failure.\n"
                "Using hardware decoding (vaapi-copy).\n"
                "[vd] Decoder format: 720x576 nv12\n",
                None,
            )

    monkeypatch.setattr(diagnostics, "render_rtsp", lambda row, _camera: "rtsp://secret")
    monkeypatch.setattr(diagnostics.subprocess, "Popen", lambda *args, **kwargs: Process())
    result = probe_stream_summary({
        "camera_key": "1:64", "username": "admin", "password": "secret",
    })
    assert result["actual_width"] == 720
    assert result["actual_height"] == 576
    assert result["gpu_compatible"] is None
    assert result["status"] == "ok"


def test_summary_probe_treats_zero_container_fps_as_unknown(monkeypatch):
    class Process:
        returncode = 0

        def communicate(self, _input=None, timeout=None):
            return "[vd] Container reported FPS: 0.000000\n[vd] Decoder format: 640x360\n", None

    monkeypatch.setattr(diagnostics, "render_rtsp", lambda row, _camera: "rtsp://secret")
    monkeypatch.setattr(diagnostics.subprocess, "Popen", lambda *args, **kwargs: Process())
    result = probe_stream_summary({
        "camera_key": "1:65", "username": "admin", "password": "secret",
    })
    assert result["fps"] is None
    assert result["status"] == "ok"


def test_summary_probe_reports_connection_failure_reason(monkeypatch):
    class Process:
        returncode = 2

        def communicate(self, _input=None, timeout=None):
            return "Failed to open rtsp://secret: Connection refused\n", None

    monkeypatch.setattr(diagnostics, "render_rtsp", lambda row, _camera: "rtsp://secret")
    monkeypatch.setattr(diagnostics.subprocess, "Popen", lambda *args, **kwargs: Process())
    result = probe_stream_summary({
        "camera_key": "1:66", "username": "admin", "password": "secret",
    })
    assert result["status"] == "connection_failed"
    assert result["error"] == "connection_failed"
