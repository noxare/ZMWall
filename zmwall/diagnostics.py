"""Credential-safe, read-only stream hardware diagnostics."""

from __future__ import annotations

import os
import platform
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from .core import connect, render_rtsp
from .network import diagnostic_lines


def redact(text: str, url: str, username: str, password: str) -> str:
    redacted = text.replace(url, "<RTSP-URL>")
    for secret in (username, password):
        if secret:
            redacted = redacted.replace(secret, "<redacted>")
    return re.sub(r"(?i)(username|password)=([^&\s]+)", r"\1=<redacted>", redacted)


def camera_row(db_path: str, identifier: str):
    with connect(db_path) as db:
        rows = db.execute(
            """SELECT c.*,s.rtsp_port,s.stream_template,s.url_template,s.username,s.password,
                      zs.hostname AS zm_server_hostname,zs.resolved_ip,zs.ip_override
               FROM cameras c JOIN sites s ON s.id=c.site_id
               LEFT JOIN zm_servers zs ON zs.site_id=c.site_id AND zs.server_id=c.server_id
               WHERE c.camera_key=? OR c.zm_id=? OR lower(c.name)=lower(?)
               ORDER BY c.camera_key""",
            (identifier, identifier, identifier),
        ).fetchall()
    if not rows:
        raise ValueError(f"Keine Kamera für {identifier!r} gefunden.")
    if len(rows) > 1:
        choices = ", ".join(f"{row['camera_key']} ({row['name']})" for row in rows)
        raise ValueError(f"Kennung ist nicht eindeutig. Bitte camera_key verwenden: {choices}")
    return rows[0]


def probe_command(ignore_profile_check: bool = False) -> list[str]:
    command = [
        "mpv", "--no-config", "--no-audio", "--vo=null",
        "--hwdec=vaapi-copy", "--hwdec-software-fallback=no",
        "--frames=30", "--profile=low-latency",
        "--demuxer-lavf-o=rtsp_transport=tcp,rw_timeout=15000000",
        "--msg-level=all=no,vd=trace,ffmpeg/video=debug", "--playlist=-",
    ]
    if ignore_profile_check:
        command.insert(-1, "--vd-lavc-check-hw-profile=no")
    return command


def summary_probe_command() -> list[str]:
    """Build a short, low-impact probe for the all-camera overview."""
    return [
        "mpv", "--no-config", "--no-audio", "--vo=null",
        "--hwdec=auto-copy", "--hwdec-software-fallback=yes",
        "--vd-lavc-check-hw-profile=no", "--frames=1", "--profile=low-latency",
        "--demuxer-lavf-o=rtsp_transport=tcp,rw_timeout=10000000",
        "--msg-level=all=no,vd=trace,ffmpeg/video=debug", "--playlist=-",
    ]


def _first_match(patterns: tuple[str, ...], output: str) -> re.Match[str] | None:
    for pattern in patterns:
        match = re.search(pattern, output, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return match
    return None


def probe_stream_summary(row: Any) -> dict[str, Any]:
    """Read one frame and return credential-free stream metadata."""
    url = render_rtsp(row, row)
    try:
        process = subprocess.Popen(
            summary_probe_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True,
        )
    except OSError as error:
        return {
            "camera_key": row["camera_key"], "status": "error",
            "error": f"mpv:{type(error).__name__}",
        }
    timed_out = False
    try:
        output, _ = process.communicate(url + "\n", timeout=15)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.terminate()
        try:
            output, _ = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate()

    output = redact(output, url, str(row["username"]), str(row["password"]))
    size = _first_match((
        r"Decoder format:\s*(\d+)x(\d+)",
        r"Reinit context to\s*(\d+)x(\d+)",
    ), output)
    codec = _first_match((r"Selected decoder:\s*([^\s]+)",), output)
    profile = _first_match((r"Codec profile:\s*([^\r\n(]+)",), output)
    fps = _first_match((r"Container reported FPS:\s*([0-9.]+)",), output)
    # mpv may reject one auto-selected hardware path and successfully use a
    # later one. Evaluate the last decisive size-limit/success event instead
    # of letting an earlier backend rejection override a later GPU success.
    size_limit_position = output.rfind("Hardware does not support image size")
    hardware_used_position = output.rfind("Using hardware decoding")
    if hardware_used_position > size_limit_position:
        gpu_compatible = 1
    elif size_limit_position >= 0:
        gpu_compatible = 0
    else:
        gpu_compatible = None
    result: dict[str, Any] = {
        "camera_key": row["camera_key"],
        "actual_width": int(size.group(1)) if size else None,
        "actual_height": int(size.group(2)) if size else None,
        "codec": codec.group(1) if codec else None,
        "profile": profile.group(1).strip() if profile else None,
        "fps": fps.group(1) if fps else None,
        # Only report a definite incompatibility for the explicit decoder-size
        # rejection. Other failures can be transient or profile-specific.
        "gpu_compatible": gpu_compatible,
        "status": "ok" if size else ("timeout" if timed_out else "error"),
        "error": None if size else ("timeout" if timed_out else "no_metadata"),
    }
    return result


def save_stream_summary(db_path: str, result: dict[str, Any]) -> None:
    with connect(db_path) as db:
        db.execute(
            """INSERT INTO stream_diagnostics(
                 camera_key,actual_width,actual_height,codec,profile,fps,gpu_compatible,status,error,checked_at
               ) VALUES(?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(camera_key) DO UPDATE SET
                 actual_width=excluded.actual_width,actual_height=excluded.actual_height,
                 codec=excluded.codec,profile=excluded.profile,fps=excluded.fps,
                 gpu_compatible=excluded.gpu_compatible,status=excluded.status,error=excluded.error,
                 checked_at=CURRENT_TIMESTAMP""",
            (
                result["camera_key"], result.get("actual_width"), result.get("actual_height"),
                result.get("codec"), result.get("profile"), result.get("fps"),
                result.get("gpu_compatible"), result["status"], result.get("error"),
            ),
        )


def diagnose_all_cameras(
    db_path: str, progress: Any | None = None, max_workers: int = 2,
) -> list[dict[str, Any]]:
    """Probe every enabled ZoneMinder restream with bounded concurrency."""
    with connect(db_path) as db:
        rows = [
            dict(row) for row in db.execute(
                """SELECT c.*,s.rtsp_port,s.stream_template,s.url_template,s.username,s.password,
                          zs.hostname AS zm_server_hostname,zs.resolved_ip,zs.ip_override
                   FROM cameras c JOIN sites s ON s.id=c.site_id
                   LEFT JOIN zm_servers zs ON zs.site_id=c.site_id AND zs.server_id=c.server_id
                   WHERE c.enabled=1 AND c.rtsp_enabled=1 ORDER BY c.name"""
            ).fetchall()
        ]
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(2, max_workers))) as executor:
        futures = {executor.submit(probe_stream_summary, row): row for row in rows}
        for future in as_completed(futures):
            row = futures[future]
            try:
                result = future.result()
            except Exception as error:  # keep the remaining camera checks running
                result = {
                    "camera_key": row["camera_key"], "status": "error",
                    "error": type(error).__name__,
                }
            save_stream_summary(db_path, result)
            results.append(result)
            if progress:
                progress(len(results), len(rows), result)
    return results


def run_probe(
    row: Any, driver: str | None, ignore_profile_check: bool = False,
) -> tuple[int, str]:
    url = render_rtsp(row, row)
    env = dict(os.environ)
    if driver:
        env["LIBVA_DRIVER_NAME"] = driver
    else:
        env.pop("LIBVA_DRIVER_NAME", None)
    try:
        process = subprocess.Popen(
            probe_command(ignore_profile_check), env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True,
        )
    except OSError as error:
        return 127, f"mpv konnte nicht gestartet werden: {type(error).__name__}"
    try:
        output, _ = process.communicate(url + "\n", timeout=20)
    except subprocess.TimeoutExpired:
        process.terminate()
        output, _ = process.communicate(timeout=3)
        output += "\nDiagnose nach 20 Sekunden beendet.\n"
    safe_output = redact(output, url, str(row["username"]), str(row["password"]))
    return process.returncode or 0, safe_output[-200_000:]


def _mpv_version() -> str:
    try:
        result = subprocess.run(
            ["mpv", "--version"], check=False, capture_output=True, text=True, timeout=3,
        )
        return result.stdout.splitlines()[0] if result.stdout else "unbekannt"
    except (OSError, subprocess.SubprocessError):
        return "nicht verfügbar"


def diagnose_camera(
    db_path: str, identifier: str, version: str, hardware: dict[str, str],
) -> str:
    row = camera_row(db_path, identifier)
    lines = [
        "ZM Wall Streamdiagnose",
        f"Zeit: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"ZM Wall: {version}",
        f"System: {platform.platform()}",
        f"mpv: {_mpv_version()}",
        f"CPU: {hardware.get('cpu', 'unbekannt')}",
        f"GPU: {hardware.get('gpu', 'unbekannt')}",
        *diagnostic_lines(),
        f"Kamera: {row['name']} (ID {row['zm_id']}, key {row['camera_key']})",
    ]
    drivers: list[str | None] = [None]
    if any(Path("/usr/lib").glob("*/dri/i965_drv_video.so")):
        drivers.append("i965")
    for ignore_profile_check in (False, True):
        for driver in drivers:
            label = driver or "Systemstandard"
            mode = "Profilprüfung deaktiviert" if ignore_profile_check else "normale Profilprüfung"
            returncode, output = run_probe(row, driver, ignore_profile_check)
            lines.extend([
                "", f"===== VAAPI-Treiber: {label} · {mode} =====",
                output.strip() or "mpv lieferte keine Decoderdiagnose.",
                f"Ergebniscode: {returncode}",
            ])
    return "\n".join(lines) + "\n"
