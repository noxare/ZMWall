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
from urllib.parse import quote, urlsplit

from .core import connect, render_rtsp
from .network import diagnostic_lines


def redact(text: str, url: str, username: str, password: str) -> str:
    redacted = text.replace(url, "<RTSP-URL>")
    for secret in (username, password):
        if secret:
            redacted = redacted.replace(secret, "<redacted>")
            redacted = redacted.replace(quote(secret, safe=""), "<redacted>")
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
        # Keep general RTSP/demuxer errors visible. all=no used to hide the
        # reason whenever mpv failed before opening the video decoder.
        "--msg-level=all=info,vd=trace,ffmpeg/video=debug", "--playlist=-",
    ]
    if ignore_profile_check:
        command.insert(-1, "--vd-lavc-check-hw-profile=no")
    return command


def summary_probe_command() -> list[str]:
    """Build a short software probe for reachability and stream metadata."""
    return [
        "mpv", "--no-config", "--no-audio", "--vo=null",
        "--hwdec=no", "--frames=1", "--profile=low-latency",
        "--demuxer-lavf-o=rtsp_transport=tcp,rw_timeout=10000000",
        "--msg-level=all=warn,vd=trace,ffmpeg/video=debug", "--playlist=-",
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
    fps_match = _first_match((r"Container reported FPS:\s*([0-9.]+)",), output)
    fps_value = fps_match.group(1) if fps_match else None
    if fps_value and float(fps_value) <= 0:
        fps_value = None
    lowered = output.lower()
    if timed_out:
        status, error = "timeout", "timeout"
    elif size:
        status, error = "ok", None
    elif any(value in lowered for value in ("401 unauthorized", "403 forbidden", "authentication failed")):
        status, error = "authentication_failed", "authentication_failed"
    elif "404 not found" in lowered:
        status, error = "not_found", "not_found"
    elif any(value in lowered for value in (
        "connection refused", "network is unreachable", "no route to host",
        "failed to resolve", "name or service not known", "connection timed out",
        "couldn't open", "could not open",
    )):
        status, error = "connection_failed", "connection_failed"
    elif any(value in lowered for value in ("error while decoding", "failed to decode", "decoder failed")):
        status, error = "decoder_failed", "decoder_failed"
    elif process.returncode:
        status, error = "process_error", f"mpv_exit_{process.returncode}"
    else:
        status, error = "no_metadata", "no_video_metadata"
    result: dict[str, Any] = {
        "camera_key": row["camera_key"],
        "actual_width": int(size.group(1)) if size else None,
        "actual_height": int(size.group(2)) if size else None,
        "codec": codec.group(1) if codec else None,
        "profile": profile.group(1).strip() if profile else None,
        "fps": fps_value,
        # GPU suitability is intentionally not inferred here. It depends on
        # hardware, driver, decoder capacity and profile and belongs to the
        # detailed diagnostic or the actual running player's CPU/GPU status.
        "gpu_compatible": None,
        "status": status,
        "error": error,
    }
    return result


def save_stream_summary(db_path: str, result: dict[str, Any]) -> None:
    with connect(db_path) as db:
        db.execute(
            """INSERT INTO stream_diagnostics(
                 camera_key,actual_width,actual_height,codec,profile,fps,gpu_compatible,
                 status,error,checked_at,probe_status,probe_error,probe_width,probe_height,
                 probe_checked_at,metadata_source
               ) VALUES(?,?,?,?,?,?,NULL,?,?,CURRENT_TIMESTAMP,?,?,?,?,CURRENT_TIMESTAMP,'batch')
               ON CONFLICT(camera_key) DO UPDATE SET
                 actual_width=CASE WHEN excluded.probe_status='ok' THEN excluded.actual_width ELSE stream_diagnostics.actual_width END,
                 actual_height=CASE WHEN excluded.probe_status='ok' THEN excluded.actual_height ELSE stream_diagnostics.actual_height END,
                 codec=CASE WHEN excluded.probe_status='ok' THEN excluded.codec ELSE stream_diagnostics.codec END,
                 profile=CASE WHEN excluded.probe_status='ok' THEN excluded.profile ELSE stream_diagnostics.profile END,
                 fps=CASE WHEN excluded.probe_status='ok' THEN excluded.fps ELSE stream_diagnostics.fps END,
                 gpu_compatible=NULL,status=excluded.status,error=excluded.error,
                 checked_at=CASE WHEN excluded.probe_status='ok' THEN CURRENT_TIMESTAMP ELSE stream_diagnostics.checked_at END,
                 probe_status=excluded.probe_status,probe_error=excluded.probe_error,
                 probe_width=CASE WHEN excluded.probe_status='ok' THEN excluded.probe_width ELSE stream_diagnostics.probe_width END,
                 probe_height=CASE WHEN excluded.probe_status='ok' THEN excluded.probe_height ELSE stream_diagnostics.probe_height END,
                 probe_checked_at=CURRENT_TIMESTAMP,
                 metadata_source=CASE WHEN excluded.probe_status='ok' THEN 'batch' ELSE stream_diagnostics.metadata_source END""",
            (
                result["camera_key"], result.get("actual_width"), result.get("actual_height"),
                result.get("codec"), result.get("profile"), result.get("fps"),
                result["status"], result.get("error"), result["status"], result.get("error"),
                result.get("actual_width"), result.get("actual_height"),
            ),
        )


def diagnose_all_cameras(
    db_path: str, progress: Any | None = None, max_workers: int = 1,
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


def interpret_probe(returncode: int, output: str) -> str:
    """Summarize the decisive result without replacing the original mpv log."""
    lowered = output.lower()
    if "using hardware decoding" in lowered:
        return "GPU-Decoding wurde initialisiert."
    if "hardware does not support image size" in lowered:
        return "Die erkannte Auflösung überschreitet die Grenze dieses Hardwaredecoders."
    if "hardware accelerator failed to decode" in lowered or "could not copy back" in lowered:
        return "Der Hardwaredecoder startete, konnte den Stream aber nicht stabil dekodieren."
    if "not supported for hardware decode" in lowered:
        return "Codecprofil oder Streamparameter wurden vom Hardwaredecoder abgelehnt."
    if any(value in lowered for value in ("401 unauthorized", "403 forbidden", "authentication failed")):
        return "Die RTSP-Anmeldung wurde abgelehnt."
    if "404 not found" in lowered:
        return "Der angeforderte RTSP-Stream wurde nicht gefunden."
    if any(value in lowered for value in (
        "connection refused", "network is unreachable", "no route to host",
        "failed to resolve", "name or service not known", "connection timed out",
    )):
        return "Die RTSP-Verbindung konnte nicht aufgebaut werden."
    if "diagnose nach 20 sekunden beendet" in lowered:
        return "Der Stream lieferte innerhalb von 20 Sekunden kein auswertbares Ergebnis."
    if returncode:
        return f"mpv wurde vor einer eindeutigen Decoderentscheidung beendet (Code {returncode})."
    return "Kein eindeutiges Hardwaredecoder-Ergebnis erkannt."


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
    safe_target = urlsplit(render_rtsp(row, row))
    target_port = safe_target.port or 554
    target = f"{safe_target.hostname or 'unbekannt'}:{target_port}{safe_target.path}"
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
        f"RTSP-Ziel: {target} · Transport: TCP (Zugangsdaten ausgeblendet)",
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
                f"Einordnung: {interpret_probe(returncode, output)}",
                f"Ergebniscode: {returncode}",
            ])
    return "\n".join(lines) + "\n"
