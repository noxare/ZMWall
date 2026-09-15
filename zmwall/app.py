from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from functools import wraps
from pathlib import Path

import requests
from flask import Flask, Response, flash, g, jsonify, redirect, render_template, request, url_for

from . import __version__
from .core import (
    PlayerManager, api_url, connect, detect_outputs, init_db, parse_camera_keys,
    sync_site, update_monitor_resolution,
)
from .diagnostics import diagnose_all_cameras, diagnose_camera
from .i18n import SUPPORTED_LANGUAGES, resolve_language, translate


DB_PATH = os.getenv("ZMWALL_DB", "/var/lib/zmwall/zmwall.db")
app = Flask(__name__)
app.secret_key = os.getenv("ZMWALL_SECRET_KEY", "change-this-key")
init_db(DB_PATH)
manager = PlayerManager(DB_PATH)
APP_DIR = Path(__file__).resolve().parent.parent
UPDATE_LOG = Path(DB_PATH).parent / "update.log"
UPDATE_ORIGINS = {
    "https://github.com/noxare/ZMWall",
    "https://github.com/noxare/ZMWall.git",
    "git@github.com:noxare/ZMWall.git",
}
update_lock = threading.Lock()
diagnostic_lock = threading.Lock()
batch_state_lock = threading.Lock()
batch_state = {"state": "idle", "completed": 0, "total": 0, "camera_key": None}
update_state = {"state": "checking", "message_key": "update_searching"}


def current_language() -> str:
    if "language" not in g:
        g.language = resolve_language(request.cookies.get("zmwall_language"), request.accept_languages)
    return g.language


def t(key: str, **values: object) -> str:
    return translate(current_language(), key, **values)


def _diagnostic_class(row: object) -> str:
    configured = (row["configured_width"], row["configured_height"])
    actual = (row["actual_width"], row["actual_height"])
    if all(configured) and configured == actual:
        return "match"
    if all(configured) and all(actual):
        return "mismatch"
    return "unchecked"


def _recovery_description(stage: str | None, reason: str | None) -> str:
    if not stage or not reason:
        return t("recovery_none")
    stage_label = t(f"recovery_stage_{stage}")
    reason_label = reason.replace("_", " ") if reason.startswith("http_") else t(
        f"recovery_reason_{reason}"
    )
    if reason.startswith("http_"):
        reason_label = reason.upper().replace("_", " ")
    return f"{stage_label}: {reason_label}"


def _camera_view(row: object) -> dict[str, object]:
    camera = dict(row)
    camera["resolution_class"] = _diagnostic_class(row)
    camera["resolution_label"] = (
        f"{row['actual_width']}×{row['actual_height']}"
        if row["actual_width"] and row["actual_height"] else "—"
    )
    if row["actual_width"] and row["actual_height"]:
        actual = camera["resolution_label"]
        configured = (
            f"{row['configured_width']}×{row['configured_height']}"
            if row["configured_width"] and row["configured_height"] else t("unknown")
        )
        camera["resolution_title"] = t(
            "resolution_details", actual=actual, configured=configured,
        )
    else:
        camera["resolution_title"] = t("resolution_not_checked")
    probe_status = camera.get("probe_status")
    camera["probe_class"] = "ok" if probe_status == "ok" else (
        "unchecked" if not probe_status else "error"
    )
    camera["probe_label"] = t(f"probe_{probe_status or 'unchecked'}")
    camera["can_apply_resolution"] = (
        probe_status == "ok" and camera["resolution_class"] == "mismatch"
    )
    recovery_state = camera.get("recovery_state")
    camera["recovery_label"] = t(f"recovery_{recovery_state or 'none'}")
    camera["recovery_title"] = _recovery_description(
        camera.get("recovery_stage"), camera.get("recovery_reason"),
    )
    return camera


CAMERA_DIAGNOSTIC_JOIN = """
LEFT JOIN camera_stream_config csc ON csc.camera_key=c.camera_key
LEFT JOIN stream_diagnostics sd ON sd.camera_key=c.camera_key
"""


def localized_update_state() -> dict[str, str]:
    status = dict(update_state)
    status["message"] = t(status.pop("message_key", "update_check_failed"))
    return status


@app.context_processor
def inject_language() -> dict[str, object]:
    return {
        "t": t,
        "language": current_language(),
        "language_choice": request.cookies.get("zmwall_language", "auto"),
    }


def _git(*arguments: str, timeout: int = 25) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(APP_DIR), *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _set_update_state(state: str, message_key: str, **values: str) -> dict[str, str]:
    global update_state
    update_state = {"state": state, "message_key": message_key, **values}
    return dict(update_state)


def check_for_update() -> dict[str, str]:
    """Fetch main and cache whether a safe fast-forward update is available."""
    with update_lock:
        if update_state.get("state") == "updating":
            return dict(update_state)
        try:
            if not (APP_DIR / ".git").is_dir():
                return _set_update_state("error", "update_not_git")
            origin = _git("remote", "get-url", "origin")
            if origin.returncode or origin.stdout.strip() not in UPDATE_ORIGINS:
                return _set_update_state("error", "update_wrong_repo")
            branch = _git("branch", "--show-current")
            if branch.returncode or branch.stdout.strip() != "main":
                return _set_update_state("error", "update_wrong_branch")
            changed = _git("status", "--porcelain", "--untracked-files=no")
            if changed.returncode or changed.stdout.strip():
                return _set_update_state("error", "update_local_changes")

            fetched = _git("fetch", "--quiet", "--prune", "origin", "main", timeout=40)
            if fetched.returncode:
                return _set_update_state("error", "update_github_failed")
            local = _git("rev-parse", "HEAD")
            remote = _git("rev-parse", "origin/main")
            if local.returncode or remote.returncode:
                return _set_update_state("error", "update_version_failed")
            local_sha = local.stdout.strip()
            remote_sha = remote.stdout.strip()
            if local_sha == remote_sha:
                return _set_update_state("current", "update_current", current=local_sha[:8])
            ancestor = _git("merge-base", "--is-ancestor", local_sha, remote_sha)
            if ancestor.returncode:
                return _set_update_state("error", "update_not_fast_forward")
            return _set_update_state(
                "available",
                "update_available",
                current=local_sha[:8],
                target=remote_sha[:8],
                target_sha=remote_sha,
            )
        except (OSError, subprocess.SubprocessError):
            return _set_update_state("error", "update_check_failed")


def periodic_update_check() -> None:
    while True:
        check_for_update()
        time.sleep(300)


def _auth_sites():
    """Return enabled ZoneMinder sites that completed at least one successful sync.

    Until such a site exists, the web UI intentionally stays open so the first
    ZoneMinder connection can be configured or repaired.
    """
    with connect(DB_PATH) as db:
        return db.execute(
            """SELECT base_url,verify_tls FROM sites
               WHERE enabled=1 AND last_sync IS NOT NULL
               ORDER BY id"""
        ).fetchall()


def _zone_minder_login(base_url: str, verify_tls: bool, username: str, password: str) -> bool:
    session = requests.Session()
    session.verify = verify_tls
    try:
        response = session.post(
            api_url(base_url, "host/login.json"),
            data={"user": username, "pass": password},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        # Current ZoneMinder versions return an access token. Older API setups
        # may return a credentials query string instead.
        return bool(payload.get("access_token") or payload.get("credentials"))
    except (requests.RequestException, ValueError, TypeError):
        return False


def authorized() -> bool:
    sites = _auth_sites()
    if not sites:
        # First configuration is deliberately password-free. Authentication is
        # enabled automatically after the first successful ZoneMinder sync.
        return True

    auth = request.authorization
    if not auth or not auth.username or auth.password is None:
        return False

    # If several independent ZoneMinder installations are configured, a valid
    # account on any successfully synchronized site grants access to ZM Wall.
    return any(
        _zone_minder_login(site["base_url"], bool(site["verify_tls"]), auth.username, auth.password)
        for site in sites
    )


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not authorized():
            return Response(
                t("login_required"),
                401,
                {"WWW-Authenticate": 'Basic realm="ZoneMinder"'},
            )
        return fn(*args, **kwargs)
    return wrapped


@app.route("/")
@login_required
def index():
    with connect(DB_PATH) as db:
        sites = db.execute("SELECT * FROM sites ORDER BY name").fetchall()
        zm_servers = db.execute("SELECT * FROM zm_servers ORDER BY site_id,name").fetchall()
        cameras = db.execute("SELECT * FROM cameras ORDER BY name").fetchall()
        selectable_cameras = [
            _camera_view(row) for row in db.execute(
                f"""SELECT c.*,csc.configured_width,csc.configured_height,
                           sd.actual_width,sd.actual_height,sd.checked_at
                    FROM cameras c {CAMERA_DIAGNOSTIC_JOIN}
                    WHERE c.rtsp_enabled=1 ORDER BY c.name"""
            ).fetchall()
        ]
        screens = db.execute("SELECT * FROM screens ORDER BY output_name").fetchall()
        assignment_rows = db.execute(
            f"""SELECT tc.screen_id,tc.position,tc.camera_key,tc.sort_order,c.name,c.server_name,
                       csc.configured_width,csc.configured_height,
                       sd.actual_width,sd.actual_height,sd.checked_at
               FROM tile_cameras tc JOIN cameras c ON c.camera_key=tc.camera_key
               {CAMERA_DIAGNOSTIC_JOIN}
               WHERE c.rtsp_enabled=1 AND c.enabled=1
               ORDER BY tc.screen_id,tc.position,tc.sort_order"""
        ).fetchall()
        assignments = {}
        assigned_camera_keys = set()
        for row in assignment_rows:
            assignments.setdefault(f"{row['screen_id']}:{row['position']}", []).append(_camera_view(row))
            assigned_camera_keys.add(row["camera_key"])
        available_cameras = [camera for camera in selectable_cameras if camera["camera_key"] not in assigned_camera_keys]
    runtime_status = manager.runtime_status()
    return render_template(
        "index.html", sites=sites, zm_servers=zm_servers, cameras=cameras,
        selectable_cameras=selectable_cameras, available_cameras=available_cameras,
        screens=screens, assignments=assignments, outputs=detect_outputs(), version=__version__,
        update_status=localized_update_state(),
        runtime_hardware=runtime_status["hardware"],
        runtime_network=runtime_status["network"],
    )


@app.post("/language")
def set_language():
    """Store an explicit UI language or return to browser/system detection."""
    choice = request.form.get("language", "auto")
    if choice not in (*SUPPORTED_LANGUAGES, "auto"):
        choice = "auto"
    next_path = request.form.get("next", "/")
    if not next_path.startswith("/") or next_path.startswith("//"):
        next_path = "/"
    response = redirect(next_path)
    if choice == "auto":
        response.delete_cookie("zmwall_language", samesite="Lax")
    else:
        response.set_cookie(
            "zmwall_language", choice, max_age=31536000, httponly=True, samesite="Lax"
        )
    return response


@app.get("/runtime/status")
@login_required
def get_runtime_status():
    status = manager.runtime_status()
    for recovery in status.get("recoveries", {}).values():
        recovery["detail"] = _recovery_description(
            recovery.get("stage"), recovery.get("reason"),
        )
    return jsonify(status)


@app.route("/diagnostics", methods=["GET", "POST"])
@login_required
def diagnostics():
    with connect(DB_PATH) as db:
        diagnostic_cameras = db.execute(
            """SELECT camera_key,zm_id,name,server_name FROM cameras
               WHERE enabled=1 AND rtsp_enabled=1 ORDER BY name"""
        ).fetchall()
        batch_rows = db.execute(
            """SELECT c.camera_key,c.zm_id,c.name,c.server_name,c.status AS zm_status,
                      csc.configured_width,csc.configured_height,
                      COALESCE(sd.probe_width,sd.actual_width) AS actual_width,
                      COALESCE(sd.probe_height,sd.actual_height) AS actual_height,
                      sd.codec,sd.profile,sd.fps,
                      sd.checked_at,sd.probe_status,sd.probe_error,sd.probe_checked_at,
                      sd.metadata_source,rr.state AS recovery_state,
                      rr.stage AS recovery_stage,rr.reason AS recovery_reason,
                      rr.attempted_at AS recovery_attempted_at
               FROM cameras c
               LEFT JOIN camera_stream_config csc ON csc.camera_key=c.camera_key
               LEFT JOIN stream_diagnostics sd ON sd.camera_key=c.camera_key
               LEFT JOIN rtsp_recovery_events rr ON rr.camera_key=c.camera_key
               WHERE c.enabled=1 AND c.rtsp_enabled=1 ORDER BY c.name"""
        ).fetchall()
    selected = request.form.get("camera_key", "")
    result = None
    diagnostic_error = None
    if request.method == "POST":
        valid_keys = {row["camera_key"] for row in diagnostic_cameras}
        if selected not in valid_keys:
            diagnostic_error = t("invalid_camera")
        elif not diagnostic_lock.acquire(blocking=False):
            diagnostic_error = t("diagnostic_busy")
        else:
            try:
                result = diagnose_camera(DB_PATH, selected, __version__, manager.decode_hardware)
            except (ValueError, OSError, subprocess.SubprocessError) as error:
                diagnostic_error = t("diagnostic_failed", error=type(error).__name__)
            finally:
                diagnostic_lock.release()
    return render_template(
        "diagnostics.html", cameras=diagnostic_cameras, selected=selected,
        result=result, diagnostic_error=diagnostic_error, version=__version__,
        batch_rows=[_camera_view(row) for row in batch_rows],
    )


def _run_batch_diagnostics() -> None:
    def progress(completed: int, total: int, result: dict[str, object]) -> None:
        with batch_state_lock:
            batch_state.update({
                "state": "running", "completed": completed, "total": total,
                "camera_key": result.get("camera_key"),
            })

    try:
        diagnose_all_cameras(DB_PATH, progress=progress, max_workers=1)
        with batch_state_lock:
            batch_state.update({"state": "completed", "camera_key": None})
    except Exception as error:
        with batch_state_lock:
            batch_state.update({
                "state": "error", "error": type(error).__name__, "camera_key": None,
            })
    finally:
        diagnostic_lock.release()


@app.post("/diagnostics/all/start")
@login_required
def start_all_diagnostics():
    if not diagnostic_lock.acquire(blocking=False):
        return jsonify({"state": "busy", "message": t("diagnostic_busy")}), 409
    with connect(DB_PATH) as db:
        total = db.execute(
            "SELECT count(*) FROM cameras WHERE enabled=1 AND rtsp_enabled=1"
        ).fetchone()[0]
    with batch_state_lock:
        batch_state.clear()
        batch_state.update({
            "state": "running", "completed": 0, "total": total, "camera_key": None,
        })
    threading.Thread(target=_run_batch_diagnostics, daemon=True).start()
    return jsonify(dict(batch_state)), 202


@app.get("/diagnostics/all/status")
@login_required
def all_diagnostics_status():
    with batch_state_lock:
        return jsonify(dict(batch_state))


@app.post("/diagnostics/resolution/apply")
@login_required
def apply_diagnostic_resolution():
    camera_key = request.form.get("camera_key", "")
    with connect(DB_PATH) as db:
        row = db.execute(
            """SELECT c.name,sd.probe_width AS actual_width,sd.probe_height AS actual_height,
                      sd.probe_status,
                      csc.configured_width,csc.configured_height
               FROM cameras c
               JOIN stream_diagnostics sd ON sd.camera_key=c.camera_key
               LEFT JOIN camera_stream_config csc ON csc.camera_key=c.camera_key
               WHERE c.camera_key=?""",
            (camera_key,),
        ).fetchone()
    if not row or row["probe_status"] != "ok" or not row["actual_width"] or not row["actual_height"]:
        flash(t("resolution_apply_unverified"), "error")
        return redirect(url_for("diagnostics"))
    if (row["configured_width"], row["configured_height"]) == (
        row["actual_width"], row["actual_height"],
    ):
        flash(t("resolution_already_matches"), "ok")
        return redirect(url_for("diagnostics"))
    try:
        width, height = update_monitor_resolution(
            DB_PATH, camera_key, int(row["actual_width"]), int(row["actual_height"]),
        )
    except requests.RequestException as error:
        status_code = error.response.status_code if error.response is not None else None
        detail = f"HTTP {status_code}" if status_code else type(error).__name__
        flash(t("resolution_apply_failed", error=detail), "error")
    except (ValueError, RuntimeError) as error:
        flash(t("resolution_apply_failed", error=str(error)[:300]), "error")
    else:
        flash(t("resolution_applied", camera=row["name"], width=width, height=height), "ok")
    return redirect(url_for("diagnostics"))


@app.get("/updates/status")
@login_required
def get_update_status():
    return jsonify({**localized_update_state(), "version": __version__})


@app.post("/updates/check")
@login_required
def check_updates_now():
    check_for_update()
    status = localized_update_state()
    flash(status["message"], "error" if status["state"] == "error" else "ok")
    return redirect(url_for("index"))


@app.post("/updates/install")
@login_required
def install_update():
    check_for_update()
    status = localized_update_state()
    if status["state"] != "available":
        flash(status["message"], "error" if status["state"] == "error" else "ok")
        return redirect(url_for("index"))

    try:
        with UPDATE_LOG.open("ab", buffering=0) as log_handle:
            process = subprocess.Popen(
                [str(APP_DIR / "update.sh"), "--web", str(os.getpid()), status["target_sha"]],
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
    except OSError:
        _set_update_state("error", "update_process_failed")
        flash(t("update_process_failed"), "error")
        return redirect(url_for("index"))

    _set_update_state("updating", "update_installing", target=status.get("target", ""))

    def watch_failed_update() -> None:
        return_code = process.wait()
        if return_code:
            _set_update_state("error", "update_failed_log")

    threading.Thread(target=watch_failed_update, daemon=True).start()
    flash(t("update_started"), "ok")
    return redirect(url_for("index"))


@app.post("/sites")
@login_required
def add_site():
    with connect(DB_PATH) as db:
        cursor = db.execute(
            """INSERT INTO sites(name,base_url,username,password,rtsp_port,stream_template,url_template,verify_tls)
               VALUES(?,?,?,?,?,?,?,?)""",
            (request.form["name"], request.form["base_url"].rstrip("/"), request.form["username"],
             request.form["password"], int(request.form.get("rtsp_port", 20000)),
             request.form.get("stream_template") or "{id}", request.form.get("url_template") or
             "rtsp://{host}:{port}/{stream}?username={username}&password={password}",
             1 if request.form.get("verify_tls") else 0),
        )
        site_id = cursor.lastrowid
    count, error = sync_site(DB_PATH, site_id)
    flash(error or t("cameras_imported", count=count), "error" if error else "ok")
    manager.request_reload()
    return redirect(url_for("index"))


@app.post("/sites/<int:site_id>/sync")
@login_required
def sync(site_id: int):
    count, error = sync_site(DB_PATH, site_id)
    flash(error or t("cameras_updated", count=count), "error" if error else "ok")
    manager.request_reload()
    return redirect(url_for("index"))


@app.post("/sites/<int:site_id>/update")
@login_required
def update_site(site_id: int):
    values = [request.form["name"], request.form["base_url"].rstrip("/"), request.form["username"]]
    sql_password = ""
    if request.form.get("password"):
        sql_password = ",password=?"
        values.append(request.form["password"])
    values.extend([
        int(request.form.get("rtsp_port", 20000)), request.form.get("stream_template") or "{id}",
        request.form.get("url_template") or "rtsp://{host}:{port}/{stream}?username={username}&password={password}",
        1 if request.form.get("verify_tls") else 0, site_id,
    ])
    with connect(DB_PATH) as db:
        db.execute(f"""UPDATE sites SET name=?,base_url=?,username=?{sql_password},rtsp_port=?,
                       stream_template=?,url_template=?,verify_tls=? WHERE id=?""", values)
    count, error = sync_site(DB_PATH, site_id)
    flash(error or t("connection_saved", count=count), "error" if error else "ok")
    manager.request_reload()
    return redirect(url_for("index"))


@app.post("/sites/<int:site_id>/delete")
@login_required
def delete_site(site_id: int):
    with connect(DB_PATH) as db:
        db.execute("DELETE FROM sites WHERE id=?", (site_id,))
    manager.request_reload()
    return redirect(url_for("index"))


@app.post("/sites/<int:site_id>/servers/<server_id>")
@login_required
def update_zm_server(site_id: int, server_id: str):
    fallback_ip = request.form.get("ip_override", "").strip() or None
    with connect(DB_PATH) as db:
        db.execute("UPDATE zm_servers SET ip_override=? WHERE site_id=? AND server_id=?",
                   (fallback_ip, site_id, server_id))
    manager.request_reload()
    flash(t("server_fallback_saved"), "ok")
    return redirect(url_for("index"))


@app.post("/screens")
@login_required
def save_screen():
    output_name = request.form["output_name"]
    rows = max(1, min(8, int(request.form["rows"])))
    cols = max(1, min(8, int(request.form["cols"])))
    rotation_seconds = max(5, min(86400, int(request.form.get("rotation_seconds", 30))))
    with connect(DB_PATH) as db:
        existing = db.execute("SELECT id FROM screens WHERE output_name=?", (output_name,)).fetchone()
        if existing:
            screen_id = existing["id"]
            db.execute(
                "UPDATE screens SET rows=?,cols=?,rotation_seconds=? WHERE id=?",
                (rows, cols, rotation_seconds, screen_id),
            )
        else:
            screen_id = db.execute(
                "INSERT INTO screens(output_name,rows,cols,rotation_seconds) VALUES(?,?,?,?)",
                (output_name, rows, cols, rotation_seconds),
            ).lastrowid
        db.execute("DELETE FROM tiles WHERE screen_id=? AND position>=?", (screen_id, rows * cols))
        db.execute("DELETE FROM tile_cameras WHERE screen_id=? AND position>=?", (screen_id, rows * cols))
    manager.request_reload(reset_layout=True)
    flash(t("monitor_layout_saved"), "ok")
    return redirect(url_for("index"))


@app.post("/layouts")
@login_required
def save_layouts():
    """Save all visible displays atomically, including camera order per tile."""
    try:
        screen_ids = [int(value) for value in request.form.getlist("screen_id")]
    except ValueError:
        flash(t("invalid_display_id"), "error")
        return redirect(url_for("index"))

    used: set[str] = set()
    with connect(DB_PATH) as db:
        valid_cameras = {
            row["camera_key"]
            for row in db.execute("SELECT camera_key FROM cameras WHERE rtsp_enabled=1 AND enabled=1")
        }
        screens = {
            row["id"]: row
            for row in db.execute(
                f"SELECT * FROM screens WHERE id IN ({','.join('?' for _ in screen_ids)})",
                screen_ids,
            )
        } if screen_ids else {}

        for screen_id in screen_ids:
            screen = screens.get(screen_id)
            if not screen:
                continue
            rows = max(1, min(8, int(request.form.get(f"rows_{screen_id}", screen["rows"]))))
            cols = max(1, min(8, int(request.form.get(f"cols_{screen_id}", screen["cols"]))))
            rotation_seconds = max(
                5,
                min(86400, int(request.form.get(f"rotation_seconds_{screen_id}", screen["rotation_seconds"]))),
            )
            db.execute(
                "UPDATE screens SET rows=?,cols=?,rotation_seconds=? WHERE id=?",
                (rows, cols, rotation_seconds, screen_id),
            )
            db.execute("DELETE FROM tile_cameras WHERE screen_id=?", (screen_id,))
            db.execute("DELETE FROM tiles WHERE screen_id=?", (screen_id,))
            for position in range(rows * cols):
                keys = parse_camera_keys(request.form.get(f"tile_{screen_id}_{position}"))
                accepted = [key for key in keys if key in valid_cameras and key not in used]
                used.update(accepted)
                db.execute(
                    "INSERT INTO tiles(screen_id,position,camera_key) VALUES(?,?,?)",
                    (screen_id, position, accepted[0] if accepted else None),
                )
                db.executemany(
                    """INSERT INTO tile_cameras(screen_id,position,camera_key,sort_order)
                       VALUES(?,?,?,?)""",
                    [(screen_id, position, key, order) for order, key in enumerate(accepted)],
                )

    manager.request_reload(reset_layout=True)
    flash(t("all_layouts_saved"), "ok")
    return redirect(url_for("index"))


@app.post("/screens/<int:screen_id>/delete")
@login_required
def delete_screen(screen_id: int):
    with connect(DB_PATH) as db:
        db.execute("DELETE FROM screens WHERE id=?", (screen_id,))
    manager.request_reload(reset_layout=True)
    return redirect(url_for("index"))


@app.post("/cameras/<path:camera_key>")
@login_required
def update_camera(camera_key: str):
    with connect(DB_PATH) as db:
        db.execute("UPDATE cameras SET rtsp_host_override=?,stream_override=? WHERE camera_key=?",
                   (request.form.get("rtsp_host_override") or None, request.form.get("stream_override") or None, camera_key))
    manager.request_reload()
    return redirect(url_for("index"))


def periodic_sync() -> None:
    while True:
        time.sleep(300)
        with connect(DB_PATH) as db:
            site_ids = [row["id"] for row in db.execute("SELECT id FROM sites WHERE enabled=1")]
        for site_id in site_ids:
            sync_site(DB_PATH, site_id)
        manager.request_reload()


def main() -> None:
    from waitress import serve

    def stop_application(_signal_number, _frame) -> None:
        manager.close()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop_application)
    threading.Thread(target=manager.run, daemon=True).start()
    threading.Thread(target=periodic_sync, daemon=True).start()
    threading.Thread(target=periodic_update_check, daemon=True).start()
    serve(app, host=os.getenv("ZMWALL_BIND", "127.0.0.1"), port=int(os.getenv("ZMWALL_PORT", "8080")), threads=8)


if __name__ == "__main__":
    main()
