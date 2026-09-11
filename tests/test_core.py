import tempfile
from pathlib import Path

import zmwall.core as core
from zmwall.core import choose_rtsp_host, connect, init_db, render_rtsp


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
        "ip_override": "172.24.0.128",
        "resolved_ip": "172.24.0.127",
    }
    assert choose_rtsp_host(camera) == "172.24.0.128"
