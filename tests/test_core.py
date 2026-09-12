import tempfile
from pathlib import Path
from types import SimpleNamespace

import zmwall.core as core
from zmwall.core import (
    choose_rtsp_host,
    connect,
    format_geometry,
    init_db,
    parse_camera_keys,
    render_rtsp,
    rotation_index,
    seconds_until_rotation,
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


def test_preload_window_starts_shortly_before_rotation():
    assert seconds_until_rotation(30, now=10) == 20
    assert seconds_until_rotation(30, now=25) == 5
    assert seconds_until_rotation(30, now=29.5) == 0.5
    assert seconds_until_rotation(30, now=30) == 30


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


def test_player_manager_prepares_current_and_upcoming_stream(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        db_path = str(Path(directory) / "rotation.db")
        init_db(db_path)
        with connect(db_path) as db:
            site_id = db.execute(
                "INSERT INTO sites(name,base_url,username,password) VALUES(?,?,?,?)",
                ("Test", "https://zm/zm", "user", "password"),
            ).lastrowid
            db.executemany(
                """INSERT INTO cameras(camera_key,site_id,zm_id,name,rtsp_host,
                                          rtsp_enabled,rtsp_stream_name)
                   VALUES(?,?,?,?,?,?,?)""",
                [
                    ("1:4", site_id, "4", "Tor", "10.0.0.2", 1, "tor"),
                    ("1:5", site_id, "5", "Hof", "10.0.0.2", 1, "hof"),
                ],
            )
            screen_id = db.execute(
                """INSERT INTO screens(output_name,rows,cols,rotation_seconds)
                   VALUES('HDMI-1',1,1,30)"""
            ).lastrowid
            db.executemany(
                """INSERT INTO tile_cameras(screen_id,position,camera_key,sort_order)
                   VALUES(?,?,?,?)""",
                [(screen_id, 0, "1:4", 0), (screen_id, 0, "1:5", 1)],
            )

        monkeypatch.setattr(
            core,
            "detect_outputs",
            lambda: [{"name": "HDMI-1", "width": 1920, "height": 1080, "x": 0, "y": 0}],
        )
        now = [10]
        monkeypatch.setattr(core.time, "monotonic", lambda: now[0])
        current, early_upcoming = core.PlayerManager(db_path).desired()[f"{screen_id}:0"]
        assert early_upcoming is None

        now[0] = 26
        current, upcoming = core.PlayerManager(db_path).desired()[f"{screen_id}:0"]
        assert "/tor?" in current.url
        assert "--hwdec=auto,auto-copy" in current.command
        assert upcoming is not None
        assert "/hof?" in upcoming.url
        assert upcoming.geometry == (0, 0, 1920, 1080)


def test_hardware_names_are_readable(monkeypatch):
    monkeypatch.setattr(
        core.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="00:02.0 VGA compatible controller: Intel Corporation HD Graphics 5500 (rev 09)\n"
        ),
    )
    hardware = core.detect_decode_hardware()
    assert hardware["gpu"] == "Intel Corporation HD Graphics 5500"
    assert "(R)" not in hardware["cpu"]
    assert "(TM)" not in hardware["cpu"]


def test_runtime_status_groups_actual_decoders_by_monitor(monkeypatch):
    class FakeProcess:
        def poll(self):
            return None

    with tempfile.TemporaryDirectory() as directory:
        db_path = str(Path(directory) / "status.db")
        init_db(db_path)
        with connect(db_path) as db:
            screen_id = db.execute(
                "INSERT INTO screens(output_name,rows,cols) VALUES('HDMI-1',1,2)"
            ).lastrowid
        monkeypatch.setattr(
            core,
            "detect_decode_hardware",
            lambda: {"cpu": "Intel Core i5-5200U", "gpu": "Intel HD Graphics 5500"},
        )
        manager = core.PlayerManager(db_path)
        manager.players[f"{screen_id}:0"] = core.Player(
            "gpu", FakeProcess(), "/tmp/gpu.sock", label="4K-Kamera",
            decode_device="gpu", hwdec="vaapi", codec="h264",
        )
        manager.players[f"{screen_id}:1"] = core.Player(
            "cpu", FakeProcess(), "/tmp/cpu.sock", label="Substream",
            decode_device="cpu", hwdec="no", codec="h264",
        )

        status = manager.runtime_status()["screens"][str(screen_id)]
        assert status["state"] == "mixed"
        assert status["label"] == "CPU + GPU · Intel HD Graphics 5500"
        assert {stream["device"] for stream in status["streams"]} == {"cpu", "gpu"}


def test_rotation_keeps_old_player_until_preload_has_video(monkeypatch):
    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    manager = core.PlayerManager("unused.db")
    old_process = FakeProcess(10)
    next_process = FakeProcess(11)
    old = core.Player("old", old_process, "/tmp/not-created-old.sock", is_ontop=True)
    preloaded = core.Player("next", next_process, "/tmp/not-created-next.sock")
    spec = core.StreamSpec("next", ["mpv"], "rtsp://next")
    manager.players["1:0"] = old
    manager.preloads["1:0"] = preloaded
    monkeypatch.setattr(manager, "desired", lambda: {"1:0": (spec, None)})
    monkeypatch.setattr(manager, "_ready", lambda player: False)

    manager.reconcile()
    assert manager.players["1:0"] is old
    assert not old_process.terminated

    monkeypatch.setattr(manager, "_ready", lambda player: True)
    monkeypatch.setattr(manager, "_ipc", lambda player, command: {"error": "success"})
    monkeypatch.setattr(manager, "_raise", lambda player: True)
    monkeypatch.setattr(core.time, "sleep", lambda seconds: None)
    manager.reconcile()
    assert manager.players["1:0"] is preloaded
    assert old_process.terminated


def test_window_raise_uses_mpv_window_id_without_blocking_activation(monkeypatch):
    class FakeProcess:
        def poll(self):
            return None

    manager = core.PlayerManager("unused.db")
    player = core.Player(
        "next", FakeProcess(), "/tmp/not-created-next.sock", window_id="4242"
    )
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(core.subprocess, "run", fake_run)
    assert manager._raise(player)
    assert calls == [["xdotool", "windowraise", "4242"]]


def test_window_tool_timeout_does_not_block_rotation(monkeypatch):
    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    manager = core.PlayerManager("unused.db")
    old = core.Player(
        "old", FakeProcess(10), "/tmp/not-created-old.sock", is_ontop=True
    )
    replacement = core.Player(
        "next", FakeProcess(11), "/tmp/not-created-next.sock"
    )
    manager.players["1:0"] = old
    manager.preloads["1:0"] = replacement
    monkeypatch.setattr(manager, "_ipc", lambda player, command: None)
    monkeypatch.setattr(manager, "_raise", lambda player: False)
    sleeps = []
    monkeypatch.setattr(core.time, "sleep", lambda seconds: sleeps.append(seconds))

    manager._promote("1:0", replacement)
    assert manager.players["1:0"] is replacement
    assert not old.is_ontop
    assert old.process.terminated
    assert sleeps == [core.WINDOW_SWITCH_SETTLE_SECONDS]


def test_embedded_surface_switch_bypasses_window_manager(monkeypatch):
    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    class FakeWindowHost:
        def __init__(self):
            self.raised = []
            self.destroyed = []

        def raise_surface(self, surface):
            self.raised.append(surface)

        def destroy_surface(self, surface):
            self.destroyed.append(surface)

    manager = core.PlayerManager("unused.db")
    manager.window_host = FakeWindowHost()
    old_surface = object()
    next_surface = object()
    old = core.Player(
        "old", FakeProcess(20), "/tmp/not-created-old.sock",
        tile_key="1:0", surface=old_surface,
    )
    replacement = core.Player(
        "next", FakeProcess(21), "/tmp/not-created-next.sock",
        tile_key="1:0", surface=next_surface,
    )
    manager.players["1:0"] = old
    manager.preloads["1:0"] = replacement
    monkeypatch.setattr(core.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        manager, "_ipc",
        lambda *_args: (_ for _ in ()).throw(AssertionError("IPC ontop must not be used")),
    )

    manager._promote("1:0", replacement)

    assert manager.window_host.raised == [next_surface]
    assert manager.window_host.destroyed == [old_surface]
    assert old.process.terminated


def test_failed_embedded_raise_keeps_old_surface_visible(monkeypatch):
    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    class FailingWindowHost:
        def raise_surface(self, _surface):
            raise OSError("X11 unavailable")

        def destroy_surface(self, _surface):
            raise AssertionError("visible surface must not be destroyed")

    manager = core.PlayerManager("unused.db")
    manager.window_host = FailingWindowHost()
    old = core.Player(
        "old", FakeProcess(30), "/tmp/not-created-old.sock",
        tile_key="1:0", surface=object(),
    )
    replacement = core.Player(
        "next", FakeProcess(31), "/tmp/not-created-next.sock",
        tile_key="1:0", surface=object(),
    )
    manager.players["1:0"] = old
    manager.preloads["1:0"] = replacement

    manager._promote("1:0", replacement)

    assert manager.players["1:0"] is old
    assert not old.process.terminated


def test_preload_must_render_frames_stably_before_it_is_ready(monkeypatch):
    class FakeProcess:
        def poll(self):
            return None

    manager = core.PlayerManager("unused.db")
    player = core.Player("next", FakeProcess(), "/tmp/not-created-next.sock")
    now = [10.0]
    monkeypatch.setattr(core.time, "monotonic", lambda: now[0])

    def fake_ipc(_player, command):
        if command[-1] == "video-params":
            return {"error": "success", "data": {"w": 1920, "h": 1080}}
        return {"error": "success", "data": {"picture-type": "P"}}

    monkeypatch.setattr(manager, "_ipc", fake_ipc)

    assert not manager._ready(player)
    now[0] += core.PRELOAD_STABLE_SECONDS - 0.01
    assert not manager._ready(player)
    now[0] += 0.02
    assert manager._ready(player)


def test_missing_rendered_frame_resets_preload_warmup(monkeypatch):
    class FakeProcess:
        def poll(self):
            return None

    manager = core.PlayerManager("unused.db")
    player = core.Player("next", FakeProcess(), "/tmp/not-created-next.sock")
    now = [10.0]
    frame_available = [True]
    monkeypatch.setattr(core.time, "monotonic", lambda: now[0])

    def fake_ipc(_player, command):
        if command[-1] == "video-params":
            return {"error": "success", "data": {"w": 1920, "h": 1080}}
        if frame_available[0]:
            return {"error": "success", "data": {"picture-type": "P"}}
        return {"error": "property unavailable"}

    monkeypatch.setattr(manager, "_ipc", fake_ipc)

    assert not manager._ready(player)
    frame_available[0] = False
    now[0] += core.PRELOAD_STABLE_SECONDS
    assert not manager._ready(player)
    assert player.ready_since is None
