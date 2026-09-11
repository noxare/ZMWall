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
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests


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
  enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS tiles (
  screen_id INTEGER NOT NULL REFERENCES screens(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  camera_key TEXT REFERENCES cameras(camera_key) ON DELETE SET NULL,
  PRIMARY KEY(screen_id, position)
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


def api_url(base_url: str, suffix: str) -> str:
    return f"{base_url.rstrip('/')}/api/{suffix.lstrip('/')}"


def resolve_ipv4(hostname: str) -> str | None:
    try:
        return socket.gethostbyname(hostname)
    except (socket.gaierror, UnicodeError):
        return None


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
                key = f"{site_id}:{monitor_id}"
                seen.add(key)
                db.execute(
                    """INSERT INTO cameras(camera_key,site_id,zm_id,name,server_id,server_name,rtsp_host,status)
                       VALUES(?,?,?,?,?,?,?,?)
                       ON CONFLICT(camera_key) DO UPDATE SET name=excluded.name,server_id=excluded.server_id,
                       server_name=excluded.server_name,rtsp_host=excluded.rtsp_host,status=excluded.status""",
                    (key, site_id, monitor_id, monitor.get("Name") or f"Kamera {monitor_id}", server_id,
                     server.get("Name") or "", host, status_obj.get("Status") or "unbekannt"),
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
    stream = camera["stream_override"] or site["stream_template"].format(
        id=camera["zm_id"], name=camera["name"], server_id=camera["server_id"] or ""
    )
    values = {
        "host": choose_rtsp_host(camera, resolution_cache), "port": site["rtsp_port"], "stream": quote(str(stream), safe="_-./"),
        "username": quote(site["username"], safe=""), "password": quote(site["password"], safe=""),
        "id": camera["zm_id"], "name": quote(camera["name"], safe=""),
    }
    return site["url_template"].format(**values)


@dataclass
class Player:
    signature: str
    process: subprocess.Popen


class PlayerManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.players: dict[str, Player] = {}
        self.stop_event = threading.Event()
        self.reload_event = threading.Event()

    def request_reload(self) -> None:
        self.reload_event.set()

    def close(self) -> None:
        self.stop_event.set()
        for player in self.players.values():
            player.process.terminate()

    @staticmethod
    def place_window(process: subprocess.Popen, x: int, y: int, width: int, height: int, env: dict[str, str]) -> None:
        """Enforce the X11 rectangle while mpv and the window manager finish startup."""
        deadline = time.monotonic() + 5
        window_id: str | None = None
        while process.poll() is None and time.monotonic() < deadline:
            try:
                if window_id is None:
                    result = subprocess.run(
                        ["xdotool", "search", "--onlyvisible", "--pid", str(process.pid)],
                        text=True, capture_output=True, env=env, timeout=1,
                    )
                    window_ids = [item for item in result.stdout.splitlines() if item.isdigit()]
                    if not window_ids:
                        time.sleep(0.1)
                        continue
                    window_id = window_ids[-1]

                # Resizing can cause Openbox to move a window back onto the first
                # output. Move last and repeat while the RTSP video initializes,
                # because mpv may update its X11 hints once the stream is decoded.
                subprocess.run(
                    ["xdotool", "windowsize", "--sync", window_id, str(width), str(height)],
                    env=env, timeout=1,
                )
                subprocess.run(
                    ["xdotool", "windowmove", "--sync", window_id, str(x), str(y)],
                    env=env, timeout=1,
                )
            except (FileNotFoundError, subprocess.SubprocessError):
                return
            time.sleep(0.25)

    def desired(self) -> dict[str, tuple[str, list[str], str, tuple[int, int, int, int]]]:
        outputs = {str(item["name"]): item for item in detect_outputs()}
        desired: dict[str, tuple[str, list[str], str, tuple[int, int, int, int]]] = {}
        resolution_cache: dict[str, str | None] = {}
        with connect(self.db_path) as db:
            screens = db.execute("SELECT * FROM screens WHERE enabled=1").fetchall()
            for screen in screens:
                output = outputs.get(screen["output_name"])
                if not output:
                    continue
                tiles = db.execute(
                    """SELECT t.position,c.*,s.rtsp_port,s.stream_template,s.url_template,s.username,s.password,
                              zs.hostname AS zm_server_hostname,zs.resolved_ip,zs.ip_override
                       FROM tiles t LEFT JOIN cameras c ON c.camera_key=t.camera_key
                       LEFT JOIN sites s ON s.id=c.site_id
                       LEFT JOIN zm_servers zs ON zs.site_id=c.site_id AND zs.server_id=c.server_id
                       WHERE t.screen_id=? ORDER BY t.position""", (screen["id"],)
                ).fetchall()
                for tile in tiles:
                    if not tile["camera_key"]:
                        continue
                    col = tile["position"] % screen["cols"]
                    row = tile["position"] // screen["cols"]
                    if row >= screen["rows"]:
                        continue
                    x, y, width, height = tile_geometry(
                        output, row, col, screen["rows"], screen["cols"]
                    )
                    url = render_rtsp(tile, tile, resolution_cache)
                    local_x = x - int(output["x"])
                    local_y = y - int(output["y"])
                    geometry = format_geometry(width, height, local_x, local_y)
                    signature = f"{url}|{screen['output_name']}|{format_geometry(width, height, x, y)}"
                    command = [
                        "mpv", "--no-config", "--no-audio", "--no-border", "--ontop", "--keep-open=no",
                        "--force-window=immediate", "--force-window-position", "--auto-window-resize=no",
                        f"--screen-name={screen['output_name']}",
                        "--keepaspect=no", "--keepaspect-window=no", "--panscan=0", "--video-zoom=0",
                        "--no-osc", "--cursor-autohide=always",
                        "--hwdec=auto-safe", "--profile=low-latency", "--demuxer-lavf-o=rtsp_transport=tcp",
                        f"--geometry={geometry}", "--really-quiet", "--playlist=-",
                    ]
                    desired[f"{screen['id']}:{tile['position']}"] = (
                        signature, command, url, (x, y, width, height)
                    )
        return desired

    def reconcile(self) -> None:
        try:
            wanted = self.desired()
        except Exception:
            return
        for key, player in list(self.players.items()):
            if key not in wanted or wanted[key][0] != player.signature or player.process.poll() is not None:
                if player.process.poll() is None:
                    player.process.terminate()
                self.players.pop(key, None)
        env = dict(os.environ)
        env["DISPLAY"] = os.getenv("ZMWALL_DISPLAY", env.get("DISPLAY", ":0"))
        for key, (signature, command, url, placement) in wanted.items():
            if key not in self.players:
                process = subprocess.Popen(command, env=env, stdin=subprocess.PIPE, text=True)
                if process.stdin:
                    process.stdin.write(url + "\n")
                    process.stdin.close()
                self.players[key] = Player(signature, process)
                x, y, width, height = placement
                threading.Thread(
                    target=self.place_window,
                    args=(process, x, y, width, height, env), daemon=True,
                ).start()

    def run(self) -> None:
        while not self.stop_event.is_set():
            self.reconcile()
            self.reload_event.wait(5)
            self.reload_event.clear()
