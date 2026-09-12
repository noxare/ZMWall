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


PRELOAD_STABLE_SECONDS = 0.75
PRELOAD_LEAD_SECONDS = 5.0
WINDOW_COMMAND_TIMEOUT_SECONDS = 0.20
WINDOW_SWITCH_SETTLE_SECONDS = 0.05


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

    session = requests.Session()
    session.verify = bool(site["verify_tls"])
    try:
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


class PlayerManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.players: dict[str, Player] = {}
        self.preloads: dict[str, Player] = {}
        self.stop_event = threading.Event()
        self.reload_event = threading.Event()
        self._ipc_counter = 0

    def request_reload(self) -> None:
        self.reload_event.set()

    @staticmethod
    def _terminate(player: Player | None) -> None:
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
        try:
            os.unlink(player.ipc_path)
        except FileNotFoundError:
            pass

    def close(self) -> None:
        self.stop_event.set()
        for player in [*self.players.values(), *self.preloads.values()]:
            self._terminate(player)

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
                        signature = (
                            f"{url}|{screen['output_name']}|"
                            f"{format_geometry(width, height, x, y)}"
                        )
                        command = [
                            "mpv", "--no-config", "--no-audio", "--no-border", "--ontop",
                            "--keep-open=no", "--force-window=immediate",
                            "--force-window-position", "--auto-window-resize=no",
                            f"--screen-name={screen['output_name']}",
                            "--keepaspect=no", "--keepaspect-window=no", "--panscan=0",
                            "--video-zoom=0", "--no-osc", "--cursor-autohide=always",
                            "--hwdec=auto-safe", "--profile=low-latency",
                            "--demuxer-lavf-o=rtsp_transport=tcp,rw_timeout=15000000",
                            f"--geometry={geometry}", "--really-quiet", "--playlist=-",
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
                        return StreamSpec(signature, command, url, label)

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
        self._ipc_counter += 1
        safe_key = re.sub(r"[^A-Za-z0-9_.-]", "-", key)
        ipc_path = f"/tmp/zmwall-{os.getpid()}-{safe_key}-{self._ipc_counter}.sock"
        command = list(spec.command)
        if hidden:
            command[command.index("--ontop")] = "--ontop=no"
        command.insert(-1, f"--input-ipc-server={ipc_path}")
        started = time.monotonic()
        try:
            process = subprocess.Popen(command, env=env, stdin=subprocess.PIPE, text=True)
            if process.stdin:
                process.stdin.write(spec.url + "\n")
                process.stdin.close()
            player = Player(
                spec.signature, process, ipc_path, is_ontop=not hidden,
                tile_key=key, label=spec.label, launched_at=started,
            )
            switch_log(
                key, spec.label, "launch", role="preload" if hidden else "active",
                pid=process.pid,
            )
            return player
        except OSError as error:
            switch_log(key, spec.label, "launch-failed", error=type(error).__name__)
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

        if player.window_id is None:
            window = self._ipc(player, ["get_property", "window-id"])
            if window and window.get("error") == "success" and window.get("data") is not None:
                player.window_id = str(window["data"])

        now = time.monotonic()
        if player.ready_since is None:
            player.ready_since = now
            hardware = self._ipc(player, ["get_property", "hwdec-current"])
            hardware_name = (
                hardware.get("data")
                if hardware and hardware.get("error") == "success"
                else "unknown"
            )
            switch_log(
                player.tile_key, player.label, "first-frame",
                pid=getattr(player.process, "pid", "unknown"),
                window=player.window_id or "unknown", hwdec=hardware_name,
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

    def _raise(self, player: Player) -> bool:
        started = time.monotonic()
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
        if not player.is_ontop:
            ontop_started = time.monotonic()
            self._ipc(player, ["set_property", "ontop", True])
            player.is_ontop = True
            switch_log(
                key, player.label, "ontop-enabled",
                pid=getattr(player.process, "pid", "unknown"),
                duration_ms=round((time.monotonic() - ontop_started) * 1000),
            )
        raised = self._raise(player)
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

        for key in set(self.players) - set(wanted):
            self._terminate(self.players.pop(key))
        for key in set(self.preloads) - set(wanted):
            self._terminate(self.preloads.pop(key))

        for key, (current, upcoming) in wanted.items():
            active = self.players.get(key)
            preload = self.preloads.get(key)

            if active and active.process.poll() is not None:
                self._terminate(active)
                self.players.pop(key, None)
                active = None
            if preload and preload.process.poll() is not None:
                self._terminate(preload)
                self.preloads.pop(key, None)
                preload = None

            if not active:
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
                if preload and preload.signature == current.signature:
                    if self._ready(preload):
                        self._promote(key, preload)
                        active = preload
                        preload = None
                else:
                    if preload:
                        self._terminate(preload)
                    preload = self._launch(key, current, hidden=True)
                    if preload:
                        self.preloads[key] = preload

            if active and active.signature == current.signature:
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

    def run(self) -> None:
        while not self.stop_event.is_set():
            self.reconcile()
            self.reload_event.wait(1)
            self.reload_event.clear()
