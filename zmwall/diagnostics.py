"""Credential-safe, read-only stream hardware diagnostics."""

from __future__ import annotations

import os
import platform
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .core import connect, render_rtsp


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
