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
                 camera_key,actual_width,actual_height,codec,profile,gpu_compatible,status
               ) VALUES(?,?,?,?,?,?,'ok')""",
            (f"{site_id}:63", 3840, 2160, "h264", "High", 0),
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
    assert "GPU-Grenze" in configuration.text

    diagnostics_page = client.get("/diagnostics", headers=headers)
    assert diagnostics_page.status_code == 200
    assert "Alle Streams prüfen" in diagnostics_page.text
    assert "720×576" in diagnostics_page.text
    assert "3840×2160" in diagnostics_page.text
