from __future__ import annotations

import json
import os
import re
import shlex
import socket
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests
from Xlib import X, display as xdisplay, error as xerror

from .network import detect_network_status


PRELOAD_STABLE_SECONDS = 0.75
PRELOAD_LEAD_SECONDS = 5.0
WINDOW_COMMAND_TIMEOUT_SECONDS = 0.20
WINDOW_SWITCH_SETTLE_SECONDS = 0.05
MAX_CONCURRENT_HWDEC_UPGRADES = 2
HWDEC_START_TIMEOUT_SECONDS = 30.0
STREAM_START_TIMEOUT_SECONDS = 30.0
STREAM_STALL_TIMEOUT_SECONDS = 20.0


def _clean_hardware_name(value: str) -> str:
    """Return a compact, human-readable CPU/GPU model name."""
    cleaned = re.sub(r"\s*\(rev [^)]+\)\s*$", "", value).strip()
    cleaned = cleaned.replace("(R)", "").replace("(TM)", "")
    cleaned = re.sub(r"\s+CPU\s+@\s+.*$", "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def detect_decode_hardware() -> dict[str, str]:
    """Detect readable processor and graphics names without vendor assumptions."""
    cpu = "Prozessor"
    try:
        for line in Path("/proc/cpuinfo").read_text(errors="replace").splitlines():
            if line.lower().startswith("model name") and ":" in line:
                cpu = _clean_hardware_name(line.split(":", 1)[1]) or cpu
                break
    except OSError:
        pass

    gpu = "Grafikeinheit"
    try:
        result = subprocess.run(
            ["lspci"], check=False, capture_output=True, text=True, timeout=2,
        )
        for line in result.stdout.splitlines():
            if any(kind in line for kind in (
                "VGA compatible controller:", "3D controller:", "Display controller:",
            )):
                gpu = _clean_hardware_name(line.split(": ", 1)[1]) or gpu
                break
    except (OSError, subprocess.SubprocessError):
        pass
    return {"cpu": cpu, "gpu": gpu}


def detect_hwdec_strategies(hardware: dict[str, str], library_root: Path = Path("/usr/lib")) -> list[str]:
    """Build a safe decoder fallback chain from drivers actually installed."""
    strategies = ["auto", "auto-copy"]
    is_intel = "intel" in hardware.get("gpu", "").lower()
    if is_intel:
        # Some FFmpeg builds reject H.264 Baseline before VAAPI is tried even
        # though the Intel driver advertises it. This copy-back strategy is
        # attempted only after both normal, profile-checked methods failed.
        strategies.append("vaapi-copy-force-profile")
    has_i965 = any(library_root.glob("*/dri/i965_drv_video.so")) or (
        library_root / "dri/i965_drv_video.so"
    ).exists()
    if is_intel and has_i965:
        strategies.extend(["vaapi-i965", "vaapi-copy-i965"])
    return strategies


def hwdec_option(strategy: str) -> str:
    return {
        "vaapi-copy-force-profile": "vaapi-copy",
        "vaapi-i965": "vaapi",
        "vaapi-copy-i965": "vaapi-copy",
    }.get(strategy, strategy)


def hwdec_arguments(strategy: str) -> list[str]:
    arguments = [f"--hwdec={hwdec_option(strategy)}"]
    if strategy == "vaapi-copy-force-profile":
        # This is the compatibility mode proven by stream diagnostics. The
        # affected cameras report contradictory H.264 profile/reference data;
        # allowing mpv's normal fallback would silently return to CPU decoding
        # after VAAPI was initialized successfully.
        arguments.extend([
            "--vd-lavc-check-hw-profile=no",
            "--hwdec-software-fallback=no",
        ])
    return arguments


def switch_log(tile: str, camera: str, event: str, **values: Any) -> None:
    """Write timestamped, credential-free diagnostics for stream rotation."""
    details = " ".join(f"{name}={value}" for name, value in values.items())
    suffix = f" {details}" if details else ""
    timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
    print(f"{timestamp} ZM Wall switch tile={tile} camera={camera!r} event={event}{suffix}", flush=True)


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS sites (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  base_url TEXT NOT NULL,
  username TEXT NOT NULL,
  password TEXT NOT NULL,
  rtsp_port INTEGER NOT NULL DEFAULT 20000,
  stream_template TEXT NOT NULL DEFAULT '{id}',
  url_template TEXT NOT NULL DEFAULT 'rtsp://{host}:{port}/{stream}?username={username}&password={password}',
  verify_tls INTEGER NOT NULL DEFAULT 1,
  enabled INTEGER NOT NULL DEFAULT 1,
  last_sync TEXT,
  last_error TEXT
);
CREATE TABLE IF NOT EXISTS cameras (
  camera_key TEXT PRIMARY KEY,
  site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
  zm_id TEXT NOT NULL,
  name TEXT NOT NULL,
  server_id TEXT,
  server_name TEXT,
  rtsp_host TEXT NOT NULL,
  rtsp_enabled INTEGER NOT NULL DEFAULT 0,
  rtsp_stream_name TEXT,
  rtsp_host_override TEXT,
  stream_override TEXT,
  status TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  UNIQUE(site_id, zm_id)
);
CREATE TABLE IF NOT EXISTS zm_servers (
  site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
  server_id TEXT NOT NULL,
  name TEXT NOT NULL,
  hostname TEXT NOT NULL,
  resolved_ip TEXT,
  ip_override TEXT,
  status TEXT,
  PRIMARY KEY(site_id, server_id)
);
CREATE TABLE IF NOT EXISTS screens (
  id INTEGER PRIMARY KEY,
  output_name TEXT NOT NULL UNIQUE,
  rows INTEGER NOT NULL DEFAULT 2,
  cols INTEGER NOT NULL DEFAULT 2,
  rotation_seconds INTEGER NOT NULL DEFAULT 30,
  enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS tiles (
  screen_id INTEGER NOT NULL REFERENCES screens(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  camera_key TEXT REFERENCES cameras(camera_key) ON DELETE SET NULL,
  PRIMARY KEY(screen_id, position)
);
CREATE TABLE IF NOT EXISTS tile_cameras (
  screen_id INTEGER NOT NULL REFERENCES screens(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  camera_key TEXT NOT NULL UNIQUE REFERENCES cameras(camera_key) ON DELETE CASCADE,
  sort_order INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(screen_id, position, camera_key)
);
CREATE TABLE IF NOT EXISTS hwdec_preferences (
  stream_key TEXT NOT NULL,
  gpu_model TEXT NOT NULL,
  strategy TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(stream_key, gpu_model)
);
CREATE TABLE IF NOT EXISTS camera_stream_config (
  camera_key TEXT PRIMARY KEY REFERENCES cameras(camera_key) ON DELETE CASCADE,
  configured_width INTEGER,
  configured_height INTEGER,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS stream_diagnostics (
  camera_key TEXT PRIMARY KEY REFERENCES cameras(camera_key) ON DELETE CASCADE,
  actual_width INTEGER,
  actual_height INTEGER,
  codec TEXT,
  profile TEXT,
  fps TEXT,
  gpu_compatible INTEGER,
  status TEXT NOT NULL,
  error TEXT,
  checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  probe_status TEXT,
  probe_error TEXT,
  probe_width INTEGER,
  probe_height INTEGER,
  probe_checked_at TEXT,
  metadata_source TEXT
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    db = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as db:
        db.executescript(SCHEMA)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(cameras)")}
        if "rtsp_host_override" not in columns:
            db.execute("ALTER TABLE cameras ADD COLUMN rtsp_host_override TEXT")
        if "rtsp_enabled" not in columns:
            # Preserve existing layouts until the first API sync supplies the
            # authoritative RTSPServer value.
            db.execute("ALTER TABLE cameras ADD COLUMN rtsp_enabled INTEGER NOT NULL DEFAULT 1")
        if "rtsp_stream_name" not in columns:
            db.execute("ALTER TABLE cameras ADD COLUMN rtsp_stream_name TEXT")
        screen_columns = {row["name"] for row in db.execute("PRAGMA table_info(screens)")}
        if "rotation_seconds" not in screen_columns:
            db.execute("ALTER TABLE screens ADD COLUMN rotation_seconds INTEGER NOT NULL DEFAULT 30")
        diagnostic_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(stream_diagnostics)")
        }
        diagnostic_upgrades = {
            "probe_status": "TEXT", "probe_error": "TEXT",
            "probe_width": "INTEGER", "probe_height": "INTEGER",
            "probe_checked_at": "TEXT", "metadata_source": "TEXT",
        }
        for name, sql_type in diagnostic_upgrades.items():
            if name not in diagnostic_columns:
                db.execute(f"ALTER TABLE stream_diagnostics ADD COLUMN {name} {sql_type}")
        # Existing rows predate the separation and remain useful as cached
        # metadata, but are deliberately not promoted to a verified probe.
        # A new all-camera check is required before write actions are offered.
        db.execute(
            """UPDATE stream_diagnostics
               SET metadata_source=COALESCE(metadata_source,'legacy')"""
        )
        # Upgrade old one-camera-per-tile layouts without losing assignments.
        # UNIQUE(camera_key) intentionally keeps the first assignment if an old
        # configuration used the same camera in several positions.
        db.execute(
            """INSERT OR IGNORE INTO tile_cameras(screen_id,position,camera_key,sort_order)
               SELECT screen_id,position,camera_key,0 FROM tiles
               WHERE camera_key IS NOT NULL
               ORDER BY screen_id,position"""
        )


def parse_camera_keys(raw: str | None) -> list[str]:
    """Parse a layout field while preserving order and removing duplicates."""
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        value = raw.split(",")
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        key = str(item).strip()
        if key and key not in result:
            result.append(key)
    return result


def rotation_index(count: int, interval_seconds: int, now: float | None = None) -> int:
    """Return the active camera index for a rotating tile."""
    if count <= 1:
        return 0
    interval = max(5, int(interval_seconds))
    timestamp = time.monotonic() if now is None else now
    return int(timestamp // interval) % count


def seconds_until_rotation(interval_seconds: int, now: float | None = None) -> float:
    """Return the time left in the current rotation interval."""
    interval = max(5, int(interval_seconds))
    timestamp = time.monotonic() if now is None else now
    remainder = timestamp % interval
    return interval - remainder if remainder else float(interval)


def api_url(base_url: str, suffix: str) -> str:
    return f"{base_url.rstrip('/')}/api/{suffix.lstrip('/')}"


def _zone_minder_session(site: sqlite3.Row) -> tuple[requests.Session, dict[str, str]]:
    """Authenticate once and return a configured API session and parameters."""
    session = requests.Session()
    session.verify = bool(site["verify_tls"])
    login = session.post(
        api_url(site["base_url"], "host/login.json"),
        data={"user": site["username"], "pass": site["password"]}, timeout=15,
    )
    login.raise_for_status()
    auth = login.json()
    params: dict[str, str] = {}
    if auth.get("access_token"):
        params["token"] = auth["access_token"]
    elif auth.get("credentials"):
        key, value = auth["credentials"].split("=", 1)
        params[key] = value
    return session, params


def resolve_ipv4(hostname: str) -> str | None:
    try:
        return socket.gethostbyname(hostname)
    except (socket.gaierror, UnicodeError):
        return None


def zm_enabled(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def choose_rtsp_host(camera: sqlite3.Row, resolution_cache: dict[str, str | None] | None = None) -> str:
    if camera["rtsp_host_override"]:
        return camera["rtsp_host_override"]
    hostname = camera["zm_server_hostname"] or camera["rtsp_host"]
    cache = resolution_cache if resolution_cache is not None else {}
    if hostname not in cache:
        cache[hostname] = resolve_ipv4(hostname)
    if cache[hostname]:
        return hostname
    return camera["ip_override"] or camera["resolved_ip"] or hostname


def sync_site(db_path: str, site_id: int) -> tuple[int, str | None]:
    with connect(db_path) as db:
        site = db.execute("SELECT * FROM sites WHERE id=?", (site_id,)).fetchone()
    if not site:
        raise ValueError("ZoneMinder-Verbindung nicht gefunden")

    try:
        session, params = _zone_minder_session(site)

        monitors_r = session.get(api_url(site["base_url"], "monitors.json"), params=params, timeout=20)
        monitors_r.raise_for_status()
        monitors = monitors_r.json().get("monitors", [])

        servers: dict[str, dict[str, Any]] = {}
        try:
            servers_r = session.get(api_url(site["base_url"], "servers.json"), params=params, timeout=15)
            servers_r.raise_for_status()
            for item in servers_r.json().get("servers", []):
                server = item.get("Server", item)
                servers[str(server.get("Id"))] = server
        except (requests.RequestException, ValueError):
            # A single-server install may not expose useful server data.
            pass

        controller_host = urlparse(site["base_url"]).hostname or site["base_url"]
        seen: set[str] = set()
        with connect(db_path) as db:
            for server_id, server in servers.items():
                hostname = str(server.get("Hostname") or "")
                if not hostname:
                    continue
                api_ip = server.get("Ip") or server.get("IP") or server.get("Address")
                resolved_ip = resolve_ipv4(hostname) or (str(api_ip) if api_ip else None)
                db.execute(
                    """INSERT INTO zm_servers(site_id,server_id,name,hostname,resolved_ip,status)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(site_id,server_id) DO UPDATE SET name=excluded.name,hostname=excluded.hostname,
                       resolved_ip=COALESCE(excluded.resolved_ip,zm_servers.resolved_ip),status=excluded.status""",
                    (site_id, server_id, server.get("Name") or f"Server {server_id}", hostname,
                     resolved_ip, server.get("Status") or "unbekannt"),
                )
            for item in monitors:
                monitor = item.get("Monitor", item)
                monitor_id = str(monitor.get("Id", ""))
                if not monitor_id:
                    continue
                server_id = str(monitor.get("ServerId") or "")
                server = servers.get(server_id, {})
                host = server.get("Hostname") or controller_host
                status_obj = item.get("Monitor_Status") or {}
                rtsp_enabled = 1 if zm_enabled(monitor.get("RTSPServer")) else 0
                rtsp_stream_name = str(monitor.get("RTSPStreamName") or "").strip() or None
                key = f"{site_id}:{monitor_id}"
                seen.add(key)
                db.execute(
                    """INSERT INTO cameras(camera_key,site_id,zm_id,name,server_id,server_name,rtsp_host,
                                             rtsp_enabled,rtsp_stream_name,status)
                       VALUES(?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(camera_key) DO UPDATE SET name=excluded.name,server_id=excluded.server_id,
                       server_name=excluded.server_name,rtsp_host=excluded.rtsp_host,
                       rtsp_enabled=excluded.rtsp_enabled,rtsp_stream_name=excluded.rtsp_stream_name,
                       status=excluded.status""",
                    (key, site_id, monitor_id, monitor.get("Name") or f"Kamera {monitor_id}", server_id,
                     server.get("Name") or "", host, rtsp_enabled, rtsp_stream_name,
                     status_obj.get("Status") or "unbekannt"),
                )
                width = monitor.get("Width")
                height = monitor.get("Height")
                db.execute(
                    """INSERT INTO camera_stream_config(camera_key,configured_width,configured_height,updated_at)
                       VALUES(?,?,?,CURRENT_TIMESTAMP)
                       ON CONFLICT(camera_key) DO UPDATE SET
                         configured_width=excluded.configured_width,
                         configured_height=excluded.configured_height,
                         updated_at=CURRENT_TIMESTAMP""",
                    (
                        key,
                        int(width) if str(width or "").isdigit() else None,
                        int(height) if str(height or "").isdigit() else None,
                    ),
                )
            if seen:
                placeholders = ",".join("?" for _ in seen)
                db.execute(f"DELETE FROM cameras WHERE site_id=? AND camera_key NOT IN ({placeholders})", (site_id, *seen))
            db.execute("UPDATE sites SET last_sync=datetime('now'),last_error=NULL WHERE id=?", (site_id,))
        return len(seen), None
    except Exception as exc:
        message = str(exc)
        with connect(db_path) as db:
            db.execute("UPDATE sites SET last_error=? WHERE id=?", (message[:500], site_id))
        return 0, message


def update_monitor_resolution(
    db_path: str, camera_key: str, width: int, height: int,
) -> tuple[int, int]:
    """Update and verify one ZoneMinder monitor's configured stream dimensions."""
    if not (16 <= int(width) <= 16384 and 16 <= int(height) <= 16384):
        raise ValueError("Ungültige Streamauflösung")
    with connect(db_path) as db:
        row = db.execute(
            """SELECT c.zm_id,c.camera_key,s.* FROM cameras c
               JOIN sites s ON s.id=c.site_id WHERE c.camera_key=?""",
            (camera_key,),
        ).fetchone()
    if not row:
        raise ValueError("Kamera nicht gefunden")

    session, params = _zone_minder_session(row)
    endpoint = api_url(row["base_url"], f"monitors/{row['zm_id']}.json")
    response = session.put(
        endpoint, params=params,
        data={"Monitor[Width]": str(int(width)), "Monitor[Height]": str(int(height))},
        timeout=20,
    )
    response.raise_for_status()
    verification = session.get(endpoint, params=params, timeout=20)
    verification.raise_for_status()
    payload = verification.json()
    item = payload.get("monitor", payload.get("Monitor", payload))
    if isinstance(item, dict) and "Monitor" in item:
        item = item["Monitor"]
    verified = (int(item.get("Width", 0)), int(item.get("Height", 0)))
    if verified != (int(width), int(height)):
        raise RuntimeError(
            f"ZoneMinder meldet nach der Änderung weiterhin {verified[0]}×{verified[1]}"
        )
    with connect(db_path) as db:
        db.execute(
            """INSERT INTO camera_stream_config(
                 camera_key,configured_width,configured_height,updated_at
               ) VALUES(?,?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(camera_key) DO UPDATE SET
                 configured_width=excluded.configured_width,
                 configured_height=excluded.configured_height,
                 updated_at=CURRENT_TIMESTAMP""",
            (camera_key, *verified),
        )
    return verified


def reregister_monitor_rtsp(db_path: str, camera_key: str) -> None:
    """Toggle one enabled ZoneMinder RTSP restream off/on and verify it."""
    with connect(db_path) as db:
        row = db.execute(
            """SELECT c.zm_id,c.rtsp_enabled,s.* FROM cameras c
               JOIN sites s ON s.id=c.site_id WHERE c.camera_key=?""",
            (camera_key,),
        ).fetchone()
    if not row:
        raise ValueError("Kamera nicht gefunden")
    if not row["rtsp_enabled"]:
        raise ValueError("RTSP-Restream ist laut ZoneMinder-API nicht aktiviert")

    session, params = _zone_minder_session(row)
    endpoint = api_url(row["base_url"], f"monitors/{row['zm_id']}.json")

    def set_enabled(enabled: bool) -> None:
        response = session.put(
            endpoint, params=params,
            data={"Monitor[RTSPServer]": "1" if enabled else "0"}, timeout=20,
        )
        response.raise_for_status()

    disabled = False
    try:
        set_enabled(False)
        disabled = True
        time.sleep(1.0)
        set_enabled(True)
        disabled = False
        time.sleep(1.0)
    finally:
        # A partial failure must not intentionally leave the restream off.
        if disabled:
            try:
                set_enabled(True)
            except requests.RequestException:
                pass

    verification = session.get(endpoint, params=params, timeout=20)
    verification.raise_for_status()
    payload = verification.json()
    item = payload.get("monitor", payload.get("Monitor", payload))
    if isinstance(item, dict) and "Monitor" in item:
        item = item["Monitor"]
    if not isinstance(item, dict) or not zm_enabled(item.get("RTSPServer")):
        raise RuntimeError("ZoneMinder meldet den RTSP-Restream nach der Neuregistrierung als inaktiv")


def detect_outputs() -> list[dict[str, int | str]]:
    env = dict(os.environ)
    env["DISPLAY"] = os.getenv("ZMWALL_DISPLAY", env.get("DISPLAY", ":0"))
    result = subprocess.run(["xrandr", "--query"], text=True, capture_output=True, env=env, timeout=5)
    outputs = []
    for line in result.stdout.splitlines():
        match = re.match(r"^(\S+) connected(?: primary)? (\d+)x(\d+)([+-]\d+)([+-]\d+)", line)
        if match:
            name, width, height, x, y = match.groups()
            outputs.append({"name": name, "width": int(width), "height": int(height), "x": int(x), "y": int(y)})
    return outputs


def tile_geometry(output: dict[str, int | str], row: int, col: int, rows: int, cols: int) -> tuple[int, int, int, int]:
    """Return an exact grid cell, distributing remainder pixels at the edges."""
    output_x = int(output["x"])
    output_y = int(output["y"])
    output_width = int(output["width"])
    output_height = int(output["height"])
    left = output_x + (output_width * col) // cols
    right = output_x + (output_width * (col + 1)) // cols
    top = output_y + (output_height * row) // rows
    bottom = output_y + (output_height * (row + 1)) // rows
    return left, top, right - left, bottom - top


def format_geometry(width: int, height: int, x: int, y: int) -> str:
    """Return an X11 geometry string, including correct signs for negative offsets."""
    return f"{width}x{height}{x:+d}{y:+d}"


def render_rtsp(site: sqlite3.Row, camera: sqlite3.Row, resolution_cache: dict[str, str | None] | None = None) -> str:
    stream = camera["stream_override"] or camera["rtsp_stream_name"] or site["stream_template"].format(
        id=camera["zm_id"], name=camera["name"], server_id=camera["server_id"] or ""
    )
    values = {
        "host": choose_rtsp_host(camera, resolution_cache), "port": site["rtsp_port"], "stream": quote(str(stream), safe="_-./"),
        "username": quote(site["username"], safe=""), "password": quote(site["password"], safe=""),
        "id": camera["zm_id"], "name": quote(camera["name"], safe=""),
    }
    return site["url_template"].format(**values)


@dataclass(frozen=True)
class StreamSpec:
    signature: str
    command: list[str]
    url: str
    label: str = "unbekannt"
    geometry: tuple[int, int, int, int] | None = None
    stream_key: str = "unbekannt"
    decode_strategy: str = "auto"


@dataclass
class Player:
    signature: str
    process: subprocess.Popen
    ipc_path: str
    ready_since: float | None = None
    window_id: str | None = None
    is_ontop: bool = False
    tile_key: str = "unbekannt"
    label: str = "unbekannt"
    launched_at: float = 0.0
    ready_logged: bool = False
    surface: Any | None = None
    decode_device: str = "unknown"
    hwdec: str = "unknown"
    codec: str = "unknown"
    stream_key: str = "unbekannt"
    decode_strategy: str = "auto"
    last_playback_time: float | None = None
    last_progress_at: float | None = None
    failure_reason: str | None = None
    output_thread: Any | None = None


class X11WindowHost:
    """Own persistent tile containers and mpv render surfaces outside Openbox."""

    def __init__(self):
        self.display = xdisplay.Display(os.getenv("ZMWALL_DISPLAY", os.getenv("DISPLAY", ":0")))
        self.screen = self.display.screen()
        self.root = self.screen.root
        self.tiles: dict[str, dict[str, Any]] = {}

    def _tile(self, key: str, geometry: tuple[int, int, int, int]) -> dict[str, Any]:
        x, y, width, height = geometry
        tile = self.tiles.get(key)
        if tile is None:
            window = self.root.create_window(
                x, y, width, height, 0, self.screen.root_depth,
                X.InputOutput, X.CopyFromParent,
                background_pixel=self.screen.black_pixel,
                override_redirect=1,
            )
            window.set_wm_name(f"ZMWall Tile {key}")
            window.map()
            tile = {"window": window, "geometry": geometry, "surfaces": set()}
            self.tiles[key] = tile
            self.display.sync()
        elif tile["geometry"] != geometry:
            tile["window"].configure(x=x, y=y, width=width, height=height)
            for surface in tuple(tile["surfaces"]):
                surface.configure(x=0, y=0, width=width, height=height)
            tile["geometry"] = geometry
            self.display.sync()
        return tile

    def create_surface(
        self,
        key: str,
        geometry: tuple[int, int, int, int],
        below: Any | None = None,
    ) -> Any:
        tile = self._tile(key, geometry)
        _, _, width, height = geometry
        surface = tile["window"].create_window(
            0, 0, width, height, 0, self.screen.root_depth,
            X.InputOutput, X.CopyFromParent,
            background_pixel=self.screen.black_pixel,
            override_redirect=1,
        )
        if below is not None:
            surface.configure(sibling=below, stack_mode=X.Below)
        surface.map()
        tile["surfaces"].add(surface)
        self.display.sync()
        return surface

    def raise_surface(self, surface: Any) -> None:
        surface.configure(stack_mode=X.Above)
        self.display.sync()

    def destroy_surface(self, surface: Any) -> None:
        for tile in self.tiles.values():
            tile["surfaces"].discard(surface)
        try:
            surface.destroy()
            self.display.flush()
        except xerror.BadWindow:
            pass

    def retain_tiles(self, keys: set[str]) -> None:
        for key in set(self.tiles) - keys:
            tile = self.tiles.pop(key)
            try:
                tile["window"].destroy()
            except xerror.BadWindow:
                pass
        self.display.flush()

    def close(self) -> None:
        for tile in self.tiles.values():
            try:
                tile["window"].destroy()
            except xerror.BadWindow:
                pass
        self.tiles.clear()
        self.display.flush()
        self.display.close()


class PlayerManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.players: dict[str, Player] = {}
        self.preloads: dict[str, Player] = {}
        self.stop_event = threading.Event()
        self.reload_event = threading.Event()
        self.layout_reset_event = threading.Event()
        self._ipc_counter = 0
        self.window_host: X11WindowHost | None = None
        self.window_host_failed = False
        self.decode_hardware = detect_decode_hardware()
        self.hwdec_strategies = detect_hwdec_strategies(self.decode_hardware)
        self.hwdec_preferences = self._load_hwdec_preferences()
        self.rtsp_recovery_attempted: set[str] = set()
        self.rtsp_recovery_in_progress: set[str] = set()
        self.rtsp_recovery_status: dict[str, dict[str, str]] = {}
        self.rtsp_recovery_lock = threading.Lock()

    def _load_hwdec_preferences(self) -> dict[str, str]:
        """Load only strategies valid for the GPU and drivers on this client."""
        if not Path(self.db_path).exists():
            return {}
        try:
            with connect(self.db_path) as db:
                rows = db.execute(
                    "SELECT stream_key,strategy FROM hwdec_preferences WHERE gpu_model=?",
                    (self.decode_hardware.get("gpu", ""),),
                ).fetchall()
        except sqlite3.Error:
            return {}
        return {
            str(row["stream_key"]): str(row["strategy"])
            for row in rows
            if row["strategy"] in self.hwdec_strategies
        }

    def _remember_hwdec_preference(self, stream_key: str, strategy: str) -> None:
        """Persist a confirmed strategy separately for each physical GPU."""
        if strategy not in self.hwdec_strategies:
            return
        self.hwdec_preferences[stream_key] = strategy
        if not Path(self.db_path).exists():
            return
        try:
            with connect(self.db_path) as db:
                db.execute(
                    """INSERT INTO hwdec_preferences(stream_key,gpu_model,strategy,updated_at)
                       VALUES(?,?,?,CURRENT_TIMESTAMP)
                       ON CONFLICT(stream_key,gpu_model) DO UPDATE SET
                         strategy=excluded.strategy,updated_at=CURRENT_TIMESTAMP""",
                    (stream_key, self.decode_hardware.get("gpu", ""), strategy),
                )
        except sqlite3.Error:
            pass

    def _remember_stream_metadata(
        self, stream_key: str, params: dict[str, Any], track: dict[str, Any], gpu: bool,
    ) -> None:
        """Cache metadata already observed by the normal player without another connection."""
        width, height = params.get("w"), params.get("h")
        if not width or not height or not Path(self.db_path).exists():
            return
        try:
            with connect(self.db_path) as db:
                db.execute(
                    """INSERT INTO stream_diagnostics(
                         camera_key,actual_width,actual_height,codec,profile,fps,
                         gpu_compatible,status,error,checked_at,metadata_source
                       ) VALUES(?,?,?,?,?,?,?,'ok',NULL,CURRENT_TIMESTAMP,'runtime')
                       ON CONFLICT(camera_key) DO UPDATE SET
                         actual_width=excluded.actual_width,actual_height=excluded.actual_height,
                         codec=COALESCE(excluded.codec,stream_diagnostics.codec),
                         profile=COALESCE(excluded.profile,stream_diagnostics.profile),
                         fps=COALESCE(excluded.fps,stream_diagnostics.fps),
                         gpu_compatible=excluded.gpu_compatible,
                         status='ok',error=NULL,checked_at=CURRENT_TIMESTAMP,
                         metadata_source='runtime'""",
                    (
                        stream_key, int(width), int(height), track.get("codec"),
                        track.get("codec-profile"), track.get("demux-fps"),
                        1 if gpu else None,
                    ),
                )
        except (sqlite3.Error, TypeError, ValueError):
            pass

    def _next_hwdec_strategy(self, player: Player, video_track: dict[str, Any]) -> str | None:
        """Choose the next attempt, skipping a known-bad Intel Baseline detour."""
        codec = str(video_track.get("codec", player.codec)).lower()
        profile = str(video_track.get("codec-profile", "")).lower()
        forced = "vaapi-copy-force-profile"
        is_intel = "intel" in self.decode_hardware.get("gpu", "").lower()
        if (
            is_intel and codec == "h264" and profile == "baseline"
            and player.decode_strategy in {"auto", "auto-copy"}
            and forced in self.hwdec_strategies
        ):
            return forced
        try:
            index = self.hwdec_strategies.index(player.decode_strategy)
            return self.hwdec_strategies[index + 1]
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _hwdec_start_timed_out(player: Player, now: float | None = None) -> bool:
        """Detect a forced hardware player that never produced a usable frame."""
        if (
            player.decode_strategy != "vaapi-copy-force-profile"
            or player.decode_device == "gpu"
            or player.launched_at <= 0
        ):
            return False
        timestamp = time.monotonic() if now is None else now
        return timestamp - player.launched_at >= HWDEC_START_TIMEOUT_SECONDS

    def _abandon_hwdec_upgrade(self, key: str, active: Player, preload: Player) -> None:
        """Keep the visible CPU player when the GPU has no free capacity."""
        self.hwdec_preferences[preload.stream_key] = active.decode_strategy
        self._terminate(preload)
        self.preloads.pop(key, None)
        self.reload_event.set()
        switch_log(
            key, preload.label, "hwdec-capacity-fallback",
            attempted=preload.decode_strategy,
            retained=active.decode_strategy,
            timeout_seconds=HWDEC_START_TIMEOUT_SECONDS,
        )

    @staticmethod
    def _capture_player_output(player: Player) -> None:
        """Drain mpv output and retain only credential-free recovery signals."""
        output = player.process.stdout
        if output is None:
            return
        for line in output:
            if re.search(r"\b404\s*(?:stream\s*)?not\s+found\b", line, re.IGNORECASE):
                player.failure_reason = "rtsp-not-found"

    def _recover_missing_rtsp(self, player: Player) -> None:
        """Run one API re-registration attempt for the current outage."""
        stream_key = player.stream_key
        try:
            reregister_monitor_rtsp(self.db_path, stream_key)
        except (ValueError, RuntimeError, requests.RequestException) as error:
            with self.rtsp_recovery_lock:
                self.rtsp_recovery_status[stream_key] = {
                    "state": "failed", "message": type(error).__name__,
                }
            switch_log(
                player.tile_key, player.label, "rtsp-reregister-failed",
                error=type(error).__name__,
            )
        else:
            with self.rtsp_recovery_lock:
                self.rtsp_recovery_status[stream_key] = {
                    "state": "retrying", "message": "reregistered",
                }
            switch_log(player.tile_key, player.label, "rtsp-reregister-complete")
            self.reload_event.set()
        finally:
            with self.rtsp_recovery_lock:
                self.rtsp_recovery_in_progress.discard(stream_key)

    def _handle_player_failure(self, player: Player) -> None:
        if player.output_thread is not None:
            player.output_thread.join(timeout=0.25)
        if player.failure_reason != "rtsp-not-found":
            return
        with self.rtsp_recovery_lock:
            if player.stream_key in self.rtsp_recovery_attempted:
                self.rtsp_recovery_status[player.stream_key] = {
                    "state": "failed", "message": "still-not-found",
                }
                switch_log(
                    player.tile_key, player.label, "rtsp-still-not-found",
                    recovery="not-repeated",
                )
                return
            self.rtsp_recovery_attempted.add(player.stream_key)
            self.rtsp_recovery_in_progress.add(player.stream_key)
            self.rtsp_recovery_status[player.stream_key] = {
                "state": "reregistering", "message": "404-stream-not-found",
            }
        switch_log(player.tile_key, player.label, "rtsp-not-found", recovery="starting-once")
        threading.Thread(target=self._recover_missing_rtsp, args=(player,), daemon=True).start()

    def runtime_status(self) -> dict[str, Any]:
        """Return the actual decoder in use, grouped by physical monitor."""
        with connect(self.db_path) as db:
            screen_names = {
                str(row["id"]): row["output_name"]
                for row in db.execute("SELECT id,output_name FROM screens ORDER BY output_name")
            }

        screens: dict[str, dict[str, Any]] = {
            screen_id: {
                "screen_id": int(screen_id), "output_name": output_name,
                "state": "inactive", "label": "Keine aktiven Streams",
                "cpu_model": self.decode_hardware["cpu"],
                "gpu_model": self.decode_hardware["gpu"],
                "streams": [],
            }
            for screen_id, output_name in screen_names.items()
        }
        try:
            runtime_players = [
                (tile_key, player, "active")
                for tile_key, player in self.players.items()
            ] + [
                (tile_key, player, "preload")
                for tile_key, player in self.preloads.items()
            ]
        except RuntimeError:
            runtime_players = []

        for tile_key, player, role in runtime_players:
            screen_id = tile_key.split(":", 1)[0]
            screen = screens.get(screen_id)
            if screen is None or player.process.poll() is not None:
                continue
            screen["streams"].append({
                "tile": tile_key,
                "camera": player.label,
                "camera_key": player.stream_key,
                "role": role,
                "device": player.decode_device,
                "hwdec": player.hwdec,
                "codec": player.codec,
            })

        for screen in screens.values():
            devices = {item["device"] for item in screen["streams"]}
            if not screen["streams"] or devices == {"unknown"}:
                screen["state"] = "loading" if screen["streams"] else "inactive"
                screen["label"] = "Decoder wird ermittelt …" if screen["streams"] else "Keine aktiven Streams"
            elif "cpu" in devices and "gpu" in devices:
                screen["state"] = "mixed"
                screen["label"] = f"CPU + GPU · {self.decode_hardware['gpu']}"
            elif "gpu" in devices:
                screen["state"] = "gpu"
                screen["label"] = f"GPU · {self.decode_hardware['gpu']}"
            else:
                screen["state"] = "cpu"
                screen["label"] = f"CPU · {self.decode_hardware['cpu']}"
        with self.rtsp_recovery_lock:
            recoveries = {key: dict(value) for key, value in self.rtsp_recovery_status.items()}
        return {
            "hardware": dict(self.decode_hardware),
            "network": detect_network_status(),
            "screens": screens,
            "recoveries": recoveries,
        }

    def request_reload(self, reset_layout: bool = False) -> None:
        """Wake the manager and optionally discard every old grid surface.

        A layout edit may move a camera to another tile. Keeping its old frame
        visible (as we do during normal rotation) would then show that camera in
        both places until the former tile's replacement is ready.
        """
        if reset_layout:
            self.layout_reset_event.set()
        self.reload_event.set()

    def _reset_layout_players(self) -> None:
        """Remove all surfaces from the previous saved layout."""
        for player in [*self.players.values(), *self.preloads.values()]:
            self._terminate(player)
        self.players.clear()
        self.preloads.clear()
        if self.window_host is not None:
            self.window_host.retain_tiles(set())
        switch_log("all", "layout", "layout-players-reset")

    def _terminate(self, player: Player | None) -> None:
        if not player:
            return
        return_code = player.process.poll()
        if return_code is None:
            player.process.terminate()
            switch_log(
                player.tile_key, player.label, "terminate",
                pid=getattr(player.process, "pid", "unknown"),
            )
        else:
            switch_log(
                player.tile_key, player.label, "process-exited",
                pid=getattr(player.process, "pid", "unknown"), returncode=return_code,
            )
        if player.surface is not None and self.window_host is not None:
            self.window_host.destroy_surface(player.surface)
            player.surface = None
        try:
            os.unlink(player.ipc_path)
        except FileNotFoundError:
            pass

    def close(self) -> None:
        self.stop_event.set()
        for player in [*self.players.values(), *self.preloads.values()]:
            self._terminate(player)
        if self.window_host is not None:
            self.window_host.close()
            self.window_host = None

    def _get_window_host(self) -> X11WindowHost | None:
        if self.window_host is None and not self.window_host_failed:
            try:
                self.window_host = X11WindowHost()
                switch_log("all", "X11", "embedded-host-ready")
            except (OSError, xerror.DisplayConnectionError) as error:
                self.window_host_failed = True
                switch_log("all", "X11", "embedded-host-failed", error=type(error).__name__)
        return self.window_host

    def desired(self) -> dict[str, tuple[StreamSpec, StreamSpec | None]]:
        outputs = {str(item["name"]): item for item in detect_outputs()}
        desired: dict[str, tuple[StreamSpec, StreamSpec | None]] = {}
        resolution_cache: dict[str, str | None] = {}

        with connect(self.db_path) as db:
            screens = db.execute("SELECT * FROM screens WHERE enabled=1").fetchall()
            for screen in screens:
                output = outputs.get(screen["output_name"])
                if not output:
                    continue
                tiles = db.execute(
                    """SELECT tc.position,tc.sort_order,c.*,s.rtsp_port,s.stream_template,s.url_template,s.username,s.password,
                              zs.hostname AS zm_server_hostname,zs.resolved_ip,zs.ip_override
                       FROM tile_cameras tc JOIN cameras c ON c.camera_key=tc.camera_key
                       LEFT JOIN sites s ON s.id=c.site_id
                       LEFT JOIN zm_servers zs ON zs.site_id=c.site_id AND zs.server_id=c.server_id
                       WHERE tc.screen_id=? AND c.rtsp_enabled=1 AND c.enabled=1
                       ORDER BY tc.position,tc.sort_order""",
                    (screen["id"],),
                ).fetchall()

                positions: dict[int, list[sqlite3.Row]] = {}
                for tile in tiles:
                    positions.setdefault(int(tile["position"]), []).append(tile)

                for position, cameras in positions.items():
                    col = position % screen["cols"]
                    row = position // screen["cols"]
                    if row >= screen["rows"]:
                        continue
                    x, y, width, height = tile_geometry(
                        output, row, col, screen["rows"], screen["cols"]
                    )
                    local_x = x - int(output["x"])
                    local_y = y - int(output["y"])
                    geometry = format_geometry(width, height, local_x, local_y)

                    def make_spec(camera: sqlite3.Row) -> StreamSpec:
                        url = render_rtsp(camera, camera, resolution_cache)
                        stream_key = str(camera["camera_key"])
                        decode_strategy = self.hwdec_preferences.get(stream_key, "auto")
                        signature = (
                            f"{url}|{screen['output_name']}|"
                            f"{format_geometry(width, height, x, y)}|hwdec={decode_strategy}"
                        )
                        command = [
                            "mpv", "--no-config", "--no-audio", "--no-border", "--ontop",
                            "--keep-open=no", "--force-window=immediate",
                            "--force-window-position", "--auto-window-resize=no",
                            f"--screen-name={screen['output_name']}",
                            "--keepaspect=no", "--keepaspect-window=no", "--panscan=0",
                            "--video-zoom=0", "--no-osc", "--cursor-autohide=always",
                            "--profile=low-latency", *hwdec_arguments(decode_strategy),
                            "--demuxer-lavf-o=rtsp_transport=tcp,rw_timeout=15000000",
                            f"--geometry={geometry}",
                            "--msg-level=all=warn", "--playlist=-",
                        ]
                        if position == (screen["rows"] * screen["cols"]) - 1:
                            command.extend([
                                "--osd-level=1", "--osd-msg1=Strg+Alt+Ende: Abmelden",
                                "--osd-align-x=right", "--osd-align-y=bottom",
                                "--osd-font-size=14", "--osd-scale-by-window=no",
                                "--osd-margin-x=8", "--osd-margin-y=6",
                                "--osd-color=#DDFFFFFF", "--osd-outline-color=#B0000000",
                            ])
                        label = f"{camera['name']} (ID {camera['zm_id']})"
                        return StreamSpec(
                            signature, command, url, label, (x, y, width, height),
                            stream_key, decode_strategy,
                        )

                    now = time.monotonic()
                    current_index = rotation_index(
                        len(cameras), screen["rotation_seconds"], now=now
                    )
                    next_index = (current_index + 1) % len(cameras)
                    current = make_spec(cameras[current_index])
                    preload_window = min(
                        PRELOAD_LEAD_SECONDS,
                        float(max(5, int(screen["rotation_seconds"]))),
                    )
                    should_preload = (
                        len(cameras) > 1
                        and seconds_until_rotation(screen["rotation_seconds"], now=now)
                        <= preload_window
                    )
                    upcoming = make_spec(cameras[next_index]) if should_preload else None
                    desired[f"{screen['id']}:{position}"] = (current, upcoming)
        return desired

    def _launch(self, key: str, spec: StreamSpec, hidden: bool) -> Player | None:
        env = dict(os.environ)
        env["DISPLAY"] = os.getenv("ZMWALL_DISPLAY", env.get("DISPLAY", ":0"))
        if spec.decode_strategy.endswith("-i965"):
            env["LIBVA_DRIVER_NAME"] = "i965"
        self._ipc_counter += 1
        safe_key = re.sub(r"[^A-Za-z0-9_.-]", "-", key)
        ipc_path = f"/tmp/zmwall-{os.getpid()}-{safe_key}-{self._ipc_counter}.sock"
        command = list(spec.command)
        surface = None
        host = self._get_window_host() if spec.geometry is not None else None
        if host is not None and spec.geometry is not None:
            active_surface = self.players.get(key).surface if self.players.get(key) else None
            try:
                surface = host.create_surface(
                    key, spec.geometry,
                    below=active_surface if hidden else None,
                )
                command = [
                    argument for argument in command
                    if argument not in {"--ontop", "--force-window-position"}
                    and not argument.startswith("--screen-name=")
                    and not argument.startswith("--geometry=")
                ]
                command.insert(-1, f"--wid={surface.id}")
            except (OSError, xerror.XError) as error:
                switch_log(key, spec.label, "surface-create-failed", error=type(error).__name__)
                surface = None
        if surface is None and hidden:
            command[command.index("--ontop")] = "--ontop=no"
        command.insert(-1, f"--input-ipc-server={ipc_path}")
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
            if process.stdin:
                process.stdin.write(spec.url + "\n")
                process.stdin.close()
            player = Player(
                spec.signature, process, ipc_path, is_ontop=not hidden,
                tile_key=key, label=spec.label, launched_at=started,
                window_id=str(surface.id) if surface is not None else None,
                surface=surface,
                stream_key=spec.stream_key,
                decode_strategy=spec.decode_strategy,
            )
            player.output_thread = threading.Thread(
                target=self._capture_player_output, args=(player,), daemon=True,
            )
            player.output_thread.start()
            switch_log(
                key, spec.label, "launch", role="preload" if hidden else "active",
                pid=process.pid, rendering="embedded" if surface is not None else "top-level",
            )
            return player
        except OSError as error:
            switch_log(key, spec.label, "launch-failed", error=type(error).__name__)
            if surface is not None and host is not None:
                host.destroy_surface(surface)
            try:
                os.unlink(ipc_path)
            except FileNotFoundError:
                pass
            return None

    @staticmethod
    def _ipc(player: Player, command: list[Any]) -> dict[str, Any] | None:
        if player.process.poll() is not None:
            return None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(0.25)
                client.connect(player.ipc_path)
                request_body = json.dumps({"command": command}).encode() + b"\n"
                client.sendall(request_body)
                response = b""
                while b"\n" not in response:
                    chunk = client.recv(65536)
                    if not chunk:
                        break
                    response += chunk
            return json.loads(response.split(b"\n", 1)[0]) if response else None
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _ready(self, player: Player) -> bool:
        probe_started = time.monotonic()
        video_params = self._ipc(player, ["get_property", "video-params"])
        frame_info = self._ipc(player, ["get_property", "video-frame-info"])
        has_video = bool(
            video_params
            and video_params.get("error") == "success"
            and isinstance(video_params.get("data"), dict)
            and video_params["data"].get("w")
            and video_params["data"].get("h")
            and frame_info
            and frame_info.get("error") == "success"
            and isinstance(frame_info.get("data"), dict)
        )
        if not has_video:
            if player.ready_since is not None:
                switch_log(
                    player.tile_key, player.label, "frame-lost",
                    pid=getattr(player.process, "pid", "unknown"),
                )
            player.ready_since = None
            player.ready_logged = False
            return False

        with self.rtsp_recovery_lock:
            recovered = self.rtsp_recovery_status.pop(player.stream_key, None)
            self.rtsp_recovery_attempted.discard(player.stream_key)
        if recovered is not None:
            switch_log(player.tile_key, player.label, "rtsp-stream-recovered")

        now = time.monotonic()
        playback_time = self._ipc(player, ["get_property", "time-pos"])
        playback_value = (
            playback_time.get("data")
            if playback_time and playback_time.get("error") == "success"
            else None
        )
        if isinstance(playback_value, (int, float)) and not isinstance(playback_value, bool):
            position = float(playback_value)
            if (
                player.last_playback_time is None
                or abs(position - player.last_playback_time) >= 0.001
            ):
                player.last_playback_time = position
                player.last_progress_at = now

        if player.window_id is None:
            window = self._ipc(player, ["get_property", "window-id"])
            if window and window.get("error") == "success" and window.get("data") is not None:
                player.window_id = str(window["data"])

        if player.ready_since is None:
            player.ready_since = now
            hardware = self._ipc(player, ["get_property", "hwdec-current"])
            interop = self._ipc(player, ["get_property", "hwdec-interop"])
            track_list = self._ipc(player, ["get_property", "track-list"])
            hardware_name = (
                hardware.get("data")
                if hardware and hardware.get("error") == "success"
                else "unknown"
            )
            interop_name = (
                interop.get("data")
                if interop and interop.get("error") == "success"
                else "none"
            )
            tracks = (
                track_list.get("data")
                if track_list and track_list.get("error") == "success"
                and isinstance(track_list.get("data"), list)
                else []
            )
            video_track = next(
                (
                    track for track in tracks
                    if track.get("type") == "video"
                    and track.get("selected") in (True, "yes")
                ),
                {},
            )
            decoded_params = video_params.get("data", {})
            reported_hwdec = str(hardware_name or "unknown")
            if reported_hwdec == "no":
                player.hwdec = "no"
                player.decode_device = "cpu"
            elif reported_hwdec not in {"unknown", ""}:
                player.hwdec = reported_hwdec
                player.decode_device = "gpu"
            # An IPC timeout is not evidence of software decoding. Preserve a
            # previously confirmed decoder instead of demoting a working GPU
            # player and advancing to a worse fallback strategy.
            reported_codec = video_track.get("codec")
            if reported_codec:
                player.codec = str(reported_codec)
            next_strategy = self._next_hwdec_strategy(player, video_track)
            if reported_hwdec == "no" and next_strategy is not None:
                self.hwdec_preferences[player.stream_key] = next_strategy
                self.reload_event.set()
                switch_log(
                    player.tile_key, player.label, "hwdec-copy-retry",
                    pid=getattr(player.process, "pid", "unknown"),
                    codec=player.codec, from_strategy=player.decode_strategy,
                    to_strategy=next_strategy,
                )
            elif player.decode_device == "gpu":
                self._remember_hwdec_preference(player.stream_key, player.decode_strategy)
            self._remember_stream_metadata(
                player.stream_key, decoded_params, video_track, player.decode_device == "gpu",
            )
            switch_log(
                player.tile_key, player.label, "first-frame",
                pid=getattr(player.process, "pid", "unknown"),
                window=player.window_id or "unknown",
                codec=video_track.get("codec", "unknown"),
                profile=video_track.get("codec-profile", "unknown"),
                decoder=video_track.get("decoder", "unknown"),
                size=f"{decoded_params.get('w', '?')}x{decoded_params.get('h', '?')}",
                pixelformat=decoded_params.get("pixelformat", "unknown"),
                hw_pixelformat=decoded_params.get("hw-pixelformat", "none"),
                hwdec=player.hwdec, reported_hwdec=reported_hwdec,
                interop=interop_name,
                strategy=player.decode_strategy,
                launch_ms=round((now - player.launched_at) * 1000),
                probe_ms=round((now - probe_started) * 1000),
            )
            return False
        is_ready = now - player.ready_since >= PRELOAD_STABLE_SECONDS
        if is_ready and not player.ready_logged:
            player.ready_logged = True
            switch_log(
                player.tile_key, player.label, "preload-ready",
                pid=getattr(player.process, "pid", "unknown"),
                stable_ms=round((now - player.ready_since) * 1000),
                launch_ms=round((now - player.launched_at) * 1000),
            )
        return is_ready

    @staticmethod
    def _stream_watchdog_reason(player: Player, now: float | None = None) -> str | None:
        """Detect a live mpv process that stopped delivering playback progress."""
        if player.launched_at <= 0:
            return None
        timestamp = time.monotonic() if now is None else now
        if (
            player.last_progress_at is not None
            and timestamp - player.last_progress_at >= STREAM_STALL_TIMEOUT_SECONDS
        ):
            return "playback-stalled"
        if (
            player.ready_since is None
            and player.last_progress_at is None
            and timestamp - player.launched_at >= STREAM_START_TIMEOUT_SECONDS
        ):
            return "startup-timeout"
        return None

    def _discard_stalled_player(
        self, key: str, player: Player, collection: dict[str, Player], role: str, reason: str,
    ) -> None:
        stalled_for = (
            round(time.monotonic() - player.last_progress_at, 1)
            if player.last_progress_at is not None
            else round(time.monotonic() - player.launched_at, 1)
        )
        switch_log(
            key, player.label, "stream-watchdog-restart",
            role=role, reason=reason, stalled_seconds=stalled_for,
            pid=getattr(player.process, "pid", "unknown"),
        )
        self._terminate(player)
        collection.pop(key, None)
        self.reload_event.set()

    def _raise(self, player: Player) -> bool:
        started = time.monotonic()
        if player.surface is not None and self.window_host is not None:
            try:
                self.window_host.raise_surface(player.surface)
                switch_log(
                    player.tile_key, player.label, "surface-raise",
                    pid=getattr(player.process, "pid", "unknown"),
                    window=player.window_id,
                    success=True,
                    duration_ms=round((time.monotonic() - started) * 1000),
                )
                return True
            except (OSError, xerror.XError) as error:
                switch_log(
                    player.tile_key, player.label, "surface-raise",
                    pid=getattr(player.process, "pid", "unknown"),
                    window=player.window_id, success=False, error=type(error).__name__,
                )
                return False
        try:
            if player.window_id is None:
                window = self._ipc(player, ["get_property", "window-id"])
                if window and window.get("error") == "success" and window.get("data") is not None:
                    player.window_id = str(window["data"])
            if player.window_id is None:
                search = subprocess.run(
                    ["xdotool", "search", "--onlyvisible", "--pid", str(player.process.pid)],
                    check=False, capture_output=True, text=True,
                    timeout=WINDOW_COMMAND_TIMEOUT_SECONDS,
                )
                matches = search.stdout.split() if search.returncode == 0 else []
                if not matches:
                    print(
                        f"ZM Wall: kein X11-Fenster für mpv PID {player.process.pid} gefunden",
                        flush=True,
                    )
                    return False
                player.window_id = matches[-1]

            raised = subprocess.run(
                ["xdotool", "windowraise", player.window_id],
                check=False, capture_output=True,
                timeout=WINDOW_COMMAND_TIMEOUT_SECONDS,
            )
            success = raised.returncode == 0
            switch_log(
                player.tile_key, player.label, "window-raise",
                pid=getattr(player.process, "pid", "unknown"),
                window=player.window_id, success=success,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
            if not success:
                print(
                    "ZM Wall: X11-Fensterwechsel fehlgeschlagen "
                    f"(Fenster {player.window_id}, raise={raised.returncode})",
                    flush=True,
                )
            return success
        except (OSError, subprocess.SubprocessError) as error:
            print(
                f"ZM Wall: X11-Fensterwechsel nicht ausführbar ({type(error).__name__})",
                flush=True,
            )
            return False

    def _promote(self, key: str, player: Player) -> None:
        started = time.monotonic()
        old = self.players.get(key)
        switch_log(
            key, player.label, "promotion-start",
            pid=getattr(player.process, "pid", "unknown"),
            old_pid=getattr(old.process, "pid", "unknown") if old else "none",
        )
        if player.surface is None and not player.is_ontop:
            ontop_started = time.monotonic()
            self._ipc(player, ["set_property", "ontop", True])
            player.is_ontop = True
            switch_log(
                key, player.label, "ontop-enabled",
                pid=getattr(player.process, "pid", "unknown"),
                duration_ms=round((time.monotonic() - ontop_started) * 1000),
            )
        raised = self._raise(player)
        if player.surface is not None and not raised:
            switch_log(
                key, player.label, "promotion-aborted",
                pid=getattr(player.process, "pid", "unknown"),
                reason="surface-raise-failed",
            )
            return
        if not raised and old is not None and old is not player:
            # The old implementation proved that revealing the preloaded
            # window by removing its predecessor works on this hardware. Keep
            # that reliable fallback if Openbox refuses explicit activation.
            self._ipc(old, ["set_property", "ontop", False])
            old.is_ontop = False
            self._raise(player)

        # Give Openbox and the X server a short presentation cycle while the
        # old, already rendered window still covers the tile. Unlike persistent
        # double buffering, the old window is then always removed, so a failed
        # stacking request cannot freeze rotation.
        time.sleep(WINDOW_SWITCH_SETTLE_SECONDS)
        self.players[key] = player
        self.preloads.pop(key, None)
        if old is not None and old is not player:
            self._terminate(old)
        switch_log(
            key, player.label, "promotion-complete",
            pid=getattr(player.process, "pid", "unknown"),
            duration_ms=round((time.monotonic() - started) * 1000),
        )

    def reconcile(self) -> None:
        try:
            wanted = self.desired()
        except Exception:
            return

        if self.layout_reset_event.is_set():
            self.layout_reset_event.clear()
            self._reset_layout_players()

        # A stream has one saved owner. If a stale player survived at a tile
        # from an earlier layout, never let it coexist with its new owner.
        desired_owners: dict[str, str] = {}
        for owner_key, (current, upcoming) in wanted.items():
            desired_owners[current.stream_key] = owner_key
            if upcoming is not None:
                desired_owners[upcoming.stream_key] = owner_key
        for collection in (self.players, self.preloads):
            for player_key, player in list(collection.items()):
                owner_key = desired_owners.get(player.stream_key)
                if owner_key is not None and owner_key != player_key:
                    switch_log(
                        player_key, player.label, "stale-layout-owner",
                        expected_tile=owner_key,
                    )
                    self._terminate(collection.pop(player_key))

        for key in set(self.players) - set(wanted):
            self._terminate(self.players.pop(key))
        for key in set(self.preloads) - set(wanted):
            self._terminate(self.preloads.pop(key))
        if self.window_host is not None:
            self.window_host.retain_tiles(set(wanted))

        hwdec_upgrades = sum(
            1
            for key, preload in self.preloads.items()
            if (active := self.players.get(key)) is not None
            and active.stream_key == preload.stream_key
            and active.decode_strategy != preload.decode_strategy
        )

        for key, (current, upcoming) in wanted.items():
            active = self.players.get(key)
            preload = self.preloads.get(key)

            if active and active.process.poll() is not None:
                self._handle_player_failure(active)
                self._terminate(active)
                self.players.pop(key, None)
                active = None
            if preload and preload.process.poll() is not None:
                self._handle_player_failure(preload)
                self._terminate(preload)
                self.preloads.pop(key, None)
                preload = None

            if not active:
                with self.rtsp_recovery_lock:
                    recovery_running = current.stream_key in self.rtsp_recovery_in_progress
                if recovery_running:
                    continue
                if preload and preload.signature == current.signature and self._ready(preload):
                    self._promote(key, preload)
                    active = preload
                    preload = None
                else:
                    if preload:
                        self._terminate(preload)
                        self.preloads.pop(key, None)
                        preload = None
                    active = self._launch(key, current, hidden=False)
                    if active:
                        self.players[key] = active

            elif active.signature != current.signature:
                # Never remove the visible stream until its replacement has
                # decoded a real frame.
                is_hwdec_upgrade = (
                    active.stream_key == current.stream_key
                    and active.decode_strategy != current.decode_strategy
                )
                if preload and preload.signature == current.signature:
                    preload_ready = self._ready(preload)
                    if preload_ready:
                        self._promote(key, preload)
                        active = preload
                        preload = None
                        if is_hwdec_upgrade:
                            hwdec_upgrades = max(0, hwdec_upgrades - 1)
                    elif is_hwdec_upgrade and self._hwdec_start_timed_out(preload):
                        self._abandon_hwdec_upgrade(key, active, preload)
                        preload = None
                        hwdec_upgrades = max(0, hwdec_upgrades - 1)
                    elif reason := self._stream_watchdog_reason(preload):
                        self._discard_stalled_player(
                            key, preload, self.preloads, "preload", reason,
                        )
                        preload = None
                else:
                    if preload:
                        self._terminate(preload)
                    if is_hwdec_upgrade and hwdec_upgrades >= MAX_CONCURRENT_HWDEC_UPGRADES:
                        continue
                    preload = self._launch(key, current, hidden=True)
                    if preload:
                        self.preloads[key] = preload
                        if is_hwdec_upgrade:
                            hwdec_upgrades += 1

            if active and active.signature == current.signature:
                # Also inspect permanently assigned streams. Previously only
                # preloads were probed, which left their UI decoder state unknown.
                self._ready(active)
                if self._hwdec_start_timed_out(active):
                    # This can happen when a remembered GPU strategy is started
                    # directly after a layout reset but the current grid needs
                    # more decoder capacity than the hardware provides.
                    self.hwdec_preferences[active.stream_key] = "no"
                    self.reload_event.set()
                    switch_log(
                        key, active.label, "hwdec-capacity-fallback",
                        attempted=active.decode_strategy, retained="no",
                        timeout_seconds=HWDEC_START_TIMEOUT_SECONDS,
                    )
                    continue
                if reason := self._stream_watchdog_reason(active):
                    self._discard_stalled_player(
                        key, active, self.players, "active", reason,
                    )
                    replacement = self._launch(key, current, hidden=False)
                    if replacement:
                        self.players[key] = replacement
                    continue
                target = upcoming
                preload = self.preloads.get(key)
                if target is None:
                    if preload:
                        self._terminate(preload)
                        self.preloads.pop(key, None)
                elif not preload or preload.signature != target.signature:
                    if preload:
                        self._terminate(preload)
                    preload = self._launch(key, target, hidden=True)
                    if preload:
                        self.preloads[key] = preload

                # Probe the upcoming stream throughout the current interval,
                # rather than only at the rotation boundary. This lets it
                # decode and render stable frames well before it is raised.
                if preload:
                    self._ready(preload)
                    if reason := self._stream_watchdog_reason(preload):
                        self._discard_stalled_player(
                            key, preload, self.preloads, "preload", reason,
                        )

    def run(self) -> None:
        while not self.stop_event.is_set():
            self.reconcile()
            self.reload_event.wait(1)
            self.reload_event.clear()
