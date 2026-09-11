import tempfile
from pathlib import Path

import zmwall.core as core
from zmwall.core import (
    choose_rtsp_host,
    connect,
    format_geometry,
    init_db,
    parse_camera_keys,
    render_rtsp,
    rotation_index,
    tile_geometry,
    zm_enabled,
)


def test_schema_and_rtsp_template():
    with tempfile.TemporaryDirectory() as directory:
        db_path = str(Path(directory) / "test.db")
        init_db(db_path)
        with connect(db_path) as db:
            site_id = db.execute(
                "INSERT INTO sites(name,base_url,username,password) VALUES(?,?,?,?)",
                ("Test", "https://zm/zm", "user name", "p@ss&word"),
            ).lastrowid
            db.execute(
                "INSERT INTO cameras(camera_key,site_id,zm_id,name,rtsp_host) VALUES(?,?,?,?,?)",
                (f"{site_id}:100", site_id, "100", "Tor", "10.0.0.2"),
            )
            row = db.execute("""SELECT c.*,s.rtsp_port,s.stream_template,s.url_template,s.username,s.password,
                                NULL AS zm_server_hostname,NULL AS resolved_ip,NULL AS ip_override
                                FROM cameras c JOIN sites s ON s.id=c.site_id""").fetchone()
            url = render_rtsp(row, row)
        assert url == "rtsp://10.0.0.2:20000/100?username=user%20name&password=p%40ss%26word"


def test_unresolvable_hostname_uses_server_ip(monkeypatch):
    monkeypatch.setattr(core, "resolve_ipv4", lambda hostname: None)
    camera = {
        "rtsp_host_override": None,
        "zm_server_hostname": "zm-node-2.internal",
        "rtsp_host": "zm-node-2.internal",
        "ip_override": "192.0.2.10",
        "resolved_ip": "192.0.2.11",
    }
    assert choose_rtsp_host(camera) == "192.0.2.10"


def test_grid_cells_cover_complete_output_without_overlap():
    output = {"x": 1920, "y": 0, "width": 1921, "height": 1081}
    cells = [tile_geometry(output, row, col, 2, 3) for row in range(2) for col in range(3)]
    assert cells[0] == (1920, 0, 640, 540)
    assert cells[2][0] + cells[2][2] == 3841
    assert cells[3][1] + cells[3][3] == 1081


def test_geometry_uses_valid_signs_for_monitors_left_of_primary():
    assert format_geometry(640, 540, -1920, 0) == "640x540-1920+0"


def test_zoneminder_boolean_values():
    assert zm_enabled(1)
    assert zm_enabled("true")
    assert not zm_enabled(0)
    assert not zm_enabled("false")


def test_api_rtsp_stream_name_takes_precedence():
    with tempfile.TemporaryDirectory() as directory:
        db_path = str(Path(directory) / "test.db")
        init_db(db_path)
        with connect(db_path) as db:
            site_id = db.execute(
                "INSERT INTO sites(name,base_url,username,password) VALUES(?,?,?,?)",
                ("Test", "https://zm/zm", "user", "password"),
            ).lastrowid
            db.execute(
                """INSERT INTO cameras(camera_key,site_id,zm_id,name,rtsp_host,
                                          rtsp_enabled,rtsp_stream_name)
                   VALUES(?,?,?,?,?,?,?)""",
                (f"{site_id}:100", site_id, "100", "Tor", "10.0.0.2", 1, "gate-stream"),
            )
            row = db.execute(
                """SELECT c.*,s.rtsp_port,s.stream_template,s.url_template,s.username,s.password,
                          NULL AS zm_server_hostname,NULL AS resolved_ip,NULL AS ip_override
                   FROM cameras c JOIN sites s ON s.id=c.site_id"""
            ).fetchone()
            url = render_rtsp(row, row)
        assert "/gate-stream?" in url


def test_camera_key_list_preserves_order_and_removes_duplicates():
    assert parse_camera_keys('["1:4", "1:5", "1:4", ""]') == ["1:4", "1:5"]
    assert parse_camera_keys("1:4,1:5") == ["1:4", "1:5"]
    assert parse_camera_keys(None) == []


def test_rotation_index_changes_at_configured_interval():
    assert rotation_index(3, 30, now=0) == 0
    assert rotation_index(3, 30, now=29.9) == 0
    assert rotation_index(3, 30, now=30) == 1
    assert rotation_index(3, 30, now=60) == 2
    assert rotation_index(3, 30, now=90) == 0
    assert rotation_index(1, 30, now=90) == 0


def test_old_single_camera_tiles_are_migrated():
    with tempfile.TemporaryDirectory() as directory:
        db_path = str(Path(directory) / "legacy.db")
        with connect(db_path) as db:
            db.executescript(
                """
                CREATE TABLE sites (id INTEGER PRIMARY KEY, name TEXT, base_url TEXT, username TEXT, password TEXT);
                CREATE TABLE cameras (
                  camera_key TEXT PRIMARY KEY, site_id INTEGER, zm_id TEXT, name TEXT,
                  rtsp_host TEXT, rtsp_enabled INTEGER DEFAULT 1
                );
                CREATE TABLE screens (
                  id INTEGER PRIMARY KEY, output_name TEXT UNIQUE, rows INTEGER DEFAULT 2,
                  cols INTEGER DEFAULT 2, enabled INTEGER DEFAULT 1
                );
                CREATE TABLE tiles (
                  screen_id INTEGER, position INTEGER, camera_key TEXT,
                  PRIMARY KEY(screen_id, position)
                );
                INSERT INTO sites VALUES(1,'Test','https://zm','user','pass');
                INSERT INTO cameras VALUES('1:4',1,'4','Tor','zm-node',1);
                INSERT INTO screens VALUES(1,'HDMI-1',2,2,1);
                INSERT INTO tiles VALUES(1,0,'1:4');
                """
            )
        init_db(db_path)
        with connect(db_path) as db:
            screen = db.execute("SELECT rotation_seconds FROM screens WHERE id=1").fetchone()
            migrated = db.execute("SELECT * FROM tile_cameras").fetchone()
        assert screen["rotation_seconds"] == 30
        assert migrated["camera_key"] == "1:4"
        assert migrated["position"] == 0
