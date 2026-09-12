#!/usr/bin/env python3
"""Run credential-safe, read-only mpv hardware-decoder diagnostics."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from zmwall.core import connect, render_rtsp


DB_PATH = os.getenv("ZMWALL_DB", "/var/lib/zmwall/zmwall.db")


def redact(text: str, url: str, username: str, password: str) -> str:
    redacted = text.replace(url, "<RTSP-URL>")
    for secret in (username, password):
        if secret:
            redacted = redacted.replace(secret, "<redacted>")
    redacted = re.sub(r"(?i)(username|password)=([^&\s]+)", r"\1=<redacted>", redacted)
    return redacted


def camera_row(identifier: str):
    with connect(DB_PATH) as db:
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
        raise SystemExit(f"Keine Kamera für {identifier!r} gefunden.")
    if len(rows) > 1:
        choices = ", ".join(f"{row['camera_key']} ({row['name']})" for row in rows)
        raise SystemExit(f"Kennung ist nicht eindeutig. Bitte camera_key verwenden: {choices}")
    return rows[0]


def run_probe(row, driver: str | None) -> tuple[int, str]:
    url = render_rtsp(row, row)
    env = dict(os.environ)
    if driver:
        env["LIBVA_DRIVER_NAME"] = driver
    else:
        env.pop("LIBVA_DRIVER_NAME", None)
    command = [
        "mpv", "--no-config", "--no-audio", "--vo=null",
        "--hwdec=vaapi-copy", "--hwdec-software-fallback=no",
        "--frames=30", "--profile=low-latency",
        "--demuxer-lavf-o=rtsp_transport=tcp,rw_timeout=15000000",
        "--msg-level=all=no,vd=trace,ffmpeg/video=debug", "--playlist=-",
    ]
    process = subprocess.Popen(
        command, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True,
    )
    try:
        output, _ = process.communicate(url + "\n", timeout=20)
    except subprocess.TimeoutExpired:
        process.terminate()
        output, _ = process.communicate(timeout=3)
        output += "\nDiagnose nach 20 Sekunden beendet.\n"
    return process.returncode or 0, redact(
        output, url, str(row["username"]), str(row["password"]),
    )


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] in {"-h", "--help"}:
        raise SystemExit(
            "Verwendung: sudo -u zmwall /opt/zmwall/.venv/bin/python "
            "/opt/zmwall/diagnose-stream.py KAMERA-ID"
        )
    row = camera_row(sys.argv[1])
    print(f"Kamera: {row['name']} (ID {row['zm_id']}, key {row['camera_key']})")
    drivers: list[str | None] = [None]
    if any(Path("/usr/lib").glob("*/dri/i965_drv_video.so")):
        drivers.append("i965")
    for driver in drivers:
        label = driver or "Systemstandard"
        print(f"\n===== VAAPI-Treiber: {label} =====")
        returncode, output = run_probe(row, driver)
        print(output.strip() or "mpv lieferte keine Decoderdiagnose.")
        print(f"Ergebniscode: {returncode}")


if __name__ == "__main__":
    main()
