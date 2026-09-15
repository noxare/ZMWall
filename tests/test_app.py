import importlib

from zmwall.core import connect, init_db


def test_configuration_and_diagnostics_show_cached_resolution(monkeypatch, tmp_path):
    db_path = str(tmp_path / "web.db")
    monkeypatch.setenv("ZMWALL_DB", db_path)
    web = importlib.import_module("zmwall.app")
    web.DB_PATH = db_path
    init_db(db_path)
    with connect(db_path) as db:
        site_id = db.execute(
            "INSERT INTO sites(name,base_url,username,password) VALUES(?,?,?,?)",
            ("Test", "https://zm.invalid/zm", "user", "password"),
        ).lastrowid
        db.execute(
            """INSERT INTO cameras(camera_key,site_id,zm_id,name,rtsp_host,rtsp_enabled)
               VALUES(?,?,?,?,?,1)""",
            (f"{site_id}:63", site_id, "63", "Galerie", "zm.invalid"),
        )
        db.execute(
            "INSERT INTO camera_stream_config(camera_key,configured_width,configured_height) VALUES(?,?,?)",
            (f"{site_id}:63", 720, 576),
        )
        db.execute(
            """INSERT INTO stream_diagnostics(
                 camera_key,actual_width,actual_height,codec,profile,gpu_compatible,status,
                 probe_status,probe_width,probe_height,probe_checked_at
               ) VALUES(?,?,?,?,?,?,'ok','ok',?,?,CURRENT_TIMESTAMP)""",
            (f"{site_id}:63", 3840, 2160, "h264", "High", 0, 3840, 2160),
        )
        screen_id = db.execute(
            "INSERT INTO screens(output_name,rows,cols) VALUES('HDMI-1',1,1)"
        ).lastrowid
        db.execute(
            "INSERT INTO tile_cameras(screen_id,position,camera_key,sort_order) VALUES(?,?,?,0)",
            (screen_id, 0, f"{site_id}:63"),
        )

    monkeypatch.setattr(web, "detect_outputs", lambda: [])
    monkeypatch.setattr(web.manager, "runtime_status", lambda: {
        "hardware": {"cpu": "Test CPU", "gpu": "Test GPU"},
        "network": {"state": "offline", "connections": []},
        "screens": {},
    })
    client = web.app.test_client()
    headers = {"Accept-Language": "de"}
    configuration = client.get("/", headers=headers)
    assert configuration.status_code == 200
    assert "3840×2160" in configuration.text
    assert "GPU-Grenze" not in configuration.text

    diagnostics_page = client.get("/diagnostics", headers=headers)
    assert diagnostics_page.status_code == 200
    assert "Alle Streams prüfen" in diagnostics_page.text
    assert "720×576" in diagnostics_page.text
    assert "3840×2160" in diagnostics_page.text
    assert "abweichend" in diagnostics_page.text
    assert "In ZoneMinder übernehmen" in diagnostics_page.text


def test_resolution_update_uses_only_verified_server_side_probe(monkeypatch, tmp_path):
    db_path = str(tmp_path / "resolution.db")
    web = importlib.import_module("zmwall.app")
    web.DB_PATH = db_path
    init_db(db_path)
    with connect(db_path) as db:
        site_id = db.execute(
            "INSERT INTO sites(name,base_url,username,password) VALUES(?,?,?,?)",
            ("Test", "https://zm.invalid/zm", "user", "password"),
        ).lastrowid
        camera_key = f"{site_id}:63"
        db.execute(
            """INSERT INTO cameras(camera_key,site_id,zm_id,name,rtsp_host,rtsp_enabled)
               VALUES(?,?,?,?,?,1)""",
            (camera_key, site_id, "63", "Galerie", "zm.invalid"),
        )
        db.execute(
            "INSERT INTO camera_stream_config(camera_key,configured_width,configured_height) VALUES(?,?,?)",
            (camera_key, 720, 576),
        )
        db.execute(
            """INSERT INTO stream_diagnostics(
                 camera_key,actual_width,actual_height,status,probe_status
                 ,probe_width,probe_height
               ) VALUES(?,?,?,'ok','ok',?,?)""",
            (camera_key, 640, 360, 640, 360),
        )
    calls = []
    monkeypatch.setattr(
        web, "update_monitor_resolution",
        lambda path, key, width, height, username=None, password=None: calls.append(
            (path, key, width, height, username, password)
        ) or (width, height),
    )
    response = web.app.test_client().post(
        "/diagnostics/resolution/apply", data={
            "camera_key": camera_key,
            "temporary_username": "admin",
            "temporary_password": "one-shot-secret",
        },
    )
    assert response.status_code == 302
    assert calls == [(db_path, camera_key, 640, 360, "admin", "one-shot-secret")]


def test_manual_rtsp_retry_accepts_one_time_credentials(monkeypatch, tmp_path):
    db_path = str(tmp_path / "manual-retry.db")
    web = importlib.import_module("zmwall.app")
    web.DB_PATH = db_path
    init_db(db_path)
    with connect(db_path) as db:
        site_id = db.execute(
            "INSERT INTO sites(name,base_url,username,password) VALUES(?,?,?,?)",
            ("Test", "https://zm.invalid/zm", "user", "password"),
        ).lastrowid
        camera_key = f"{site_id}:63"
        db.execute(
            """INSERT INTO cameras(camera_key,site_id,zm_id,name,rtsp_host,rtsp_enabled)
               VALUES(?,?,?,?,?,1)""",
            (camera_key, site_id, "63", "Galerie", "zm.invalid"),
        )
    calls = []
    monkeypatch.setattr(
        web.manager, "reregister_rtsp_now",
        lambda key, username, password: calls.append((key, username, password))
        or (True, "stream", "reregistered"),
    )
    response = web.app.test_client().post(
        "/diagnostics/rtsp/reregister",
        data={
            "camera_key": camera_key,
            "temporary_username": "admin",
            "temporary_password": "one-shot-secret",
        },
    )
    assert response.status_code == 302
    assert calls == [(camera_key, "admin", "one-shot-secret")]
