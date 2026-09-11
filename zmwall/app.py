from __future__ import annotations

import os
import threading
import time
from functools import wraps

import requests
from flask import Flask, Response, flash, redirect, render_template, request, url_for

from .core import PlayerManager, api_url, connect, detect_outputs, init_db, sync_site


DB_PATH = os.getenv("ZMWALL_DB", "/var/lib/zmwall/zmwall.db")
app = Flask(__name__)
app.secret_key = os.getenv("ZMWALL_SECRET_KEY", "change-this-key")
init_db(DB_PATH)
manager = PlayerManager(DB_PATH)


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
                "Anmeldung mit einem gültigen ZoneMinder-Benutzer erforderlich",
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
        selectable_cameras = db.execute(
            "SELECT * FROM cameras WHERE rtsp_enabled=1 ORDER BY name"
        ).fetchall()
        screens = db.execute("SELECT * FROM screens ORDER BY output_name").fetchall()
        assignments = {f"{r['screen_id']}:{r['position']}": r["camera_key"] or "" for r in db.execute("SELECT * FROM tiles")}
    return render_template(
        "index.html", sites=sites, zm_servers=zm_servers, cameras=cameras,
        selectable_cameras=selectable_cameras, screens=screens, assignments=assignments,
        outputs=detect_outputs(),
    )


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
    flash(error or f"{count} Kameras eingelesen.", "error" if error else "ok")
    manager.request_reload()
    return redirect(url_for("index"))


@app.post("/sites/<int:site_id>/sync")
@login_required
def sync(site_id: int):
    count, error = sync_site(DB_PATH, site_id)
    flash(error or f"{count} Kameras aktualisiert.", "error" if error else "ok")
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
    flash(error or f"Verbindung gespeichert; {count} Kameras aktualisiert.", "error" if error else "ok")
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
    flash("Server-Fallback gespeichert.", "ok")
    return redirect(url_for("index"))


@app.post("/screens")
@login_required
def save_screen():
    output_name = request.form["output_name"]
    rows = max(1, min(8, int(request.form["rows"])))
    cols = max(1, min(8, int(request.form["cols"])))
    with connect(DB_PATH) as db:
        existing = db.execute("SELECT id FROM screens WHERE output_name=?", (output_name,)).fetchone()
        if existing:
            screen_id = existing["id"]
            db.execute("UPDATE screens SET rows=?,cols=? WHERE id=?", (rows, cols, screen_id))
        else:
            screen_id = db.execute("INSERT INTO screens(output_name,rows,cols) VALUES(?,?,?)", (output_name, rows, cols)).lastrowid
        db.execute("DELETE FROM tiles WHERE screen_id=? AND position>=?", (screen_id, rows * cols))
        for position in range(rows * cols):
            key = request.form.get(f"tile_{position}") or None
            db.execute("""INSERT INTO tiles(screen_id,position,camera_key) VALUES(?,?,?)
                          ON CONFLICT(screen_id,position) DO UPDATE SET camera_key=excluded.camera_key""",
                       (screen_id, position, key))
    manager.request_reload()
    flash("Monitorlayout gespeichert.", "ok")
    return redirect(url_for("index"))


@app.post("/screens/<int:screen_id>/delete")
@login_required
def delete_screen(screen_id: int):
    with connect(DB_PATH) as db:
        db.execute("DELETE FROM screens WHERE id=?", (screen_id,))
    manager.request_reload()
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
    threading.Thread(target=manager.run, daemon=True).start()
    threading.Thread(target=periodic_sync, daemon=True).start()
    serve(app, host=os.getenv("ZMWALL_BIND", "127.0.0.1"), port=int(os.getenv("ZMWALL_PORT", "8080")), threads=8)


if __name__ == "__main__":
    main()
