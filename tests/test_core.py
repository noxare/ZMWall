import io
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


def test_old_stream_metadata_is_not_promoted_to_verified_probe(tmp_path):
    db_path = str(tmp_path / "legacy-diagnostics.db")
    init_db(db_path)
    with connect(db_path) as db:
        site_id = db.execute(
            "INSERT INTO sites(name,base_url,username,password) VALUES('Test','https://zm','u','p')"
        ).lastrowid
        db.execute(
            "INSERT INTO cameras(camera_key,site_id,zm_id,name,rtsp_host) VALUES('1:4',?,?,?,?)",
            (site_id, "4", "Tor", "zm"),
        )
        db.execute(
            "INSERT INTO stream_diagnostics(camera_key,status,error) VALUES('1:4','timeout','timeout')"
        )
    init_db(db_path)
    with connect(db_path) as db:
        row = db.execute("SELECT * FROM stream_diagnostics WHERE camera_key='1:4'").fetchone()
    assert row["probe_status"] is None
    assert row["probe_error"] is None
    assert row["probe_checked_at"] is None
    assert row["metadata_source"] == "legacy"


def test_zoneminder_resolution_update_is_verified_before_local_save(monkeypatch, tmp_path):
    db_path = str(tmp_path / "zm-update.db")
    init_db(db_path)
    with connect(db_path) as db:
        site_id = db.execute(
            "INSERT INTO sites(name,base_url,username,password) VALUES('Test','https://zm/zm','u','p')"
        ).lastrowid
        camera_key = f"{site_id}:4"
        db.execute(
            "INSERT INTO cameras(camera_key,site_id,zm_id,name,rtsp_host) VALUES(?,?,?,?,?)",
            (camera_key, site_id, "4", "Tor", "zm"),
        )

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"monitor": {"Monitor": {"Width": "640", "Height": "360"}}}

    class Session:
        def __init__(self):
            self.put_data = None

        def put(self, _url, params=None, data=None, timeout=None):
            self.put_data = data
            return Response()

        def get(self, _url, params=None, timeout=None):
            return Response()

    session = Session()
    monkeypatch.setattr(core, "_zone_minder_session", lambda _site: (session, {"token": "safe"}))
    assert core.update_monitor_resolution(db_path, camera_key, 640, 360) == (640, 360)
    assert session.put_data == {"Monitor[Width]": "640", "Monitor[Height]": "360"}
    with connect(db_path) as db:
        saved = db.execute(
            "SELECT configured_width,configured_height FROM camera_stream_config WHERE camera_key=?",
            (camera_key,),
        ).fetchone()
    assert (saved["configured_width"], saved["configured_height"]) == (640, 360)


def test_rtsp_reregistration_toggles_once_and_verifies_enabled(monkeypatch, tmp_path):
    db_path = str(tmp_path / "zm-reregister.db")
    init_db(db_path)
    with connect(db_path) as db:
        site_id = db.execute(
            "INSERT INTO sites(name,base_url,username,password) VALUES('Test','https://zm/zm','u','p')"
        ).lastrowid
        camera_key = f"{site_id}:4"
        db.execute(
            """INSERT INTO cameras(camera_key,site_id,zm_id,name,rtsp_host,rtsp_enabled)
               VALUES(?,?,?,?,?,1)""",
            (camera_key, site_id, "4", "Tor", "zm"),
        )

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"monitor": {"Monitor": {"RTSPServer": "1"}}}

    class Session:
        def __init__(self):
            self.values = []

        def put(self, _url, params=None, data=None, timeout=None):
            self.values.append(data["Monitor[RTSPServer]"])
            return Response()

        def get(self, _url, params=None, timeout=None):
            return Response()

    session = Session()
    monkeypatch.setattr(core, "_zone_minder_session", lambda _site: (session, {"token": "safe"}))
    monkeypatch.setattr(core.time, "sleep", lambda _seconds: None)
    core.reregister_monitor_rtsp(db_path, camera_key)
    assert session.values == ["0", "1"]


def test_rtsp_reregistration_reports_missing_edit_permission(monkeypatch, tmp_path):
    db_path = str(tmp_path / "zm-reregister-denied.db")
    init_db(db_path)
    with connect(db_path) as db:
        site_id = db.execute(
            "INSERT INTO sites(name,base_url,username,password) VALUES('Test','https://zm/zm','u','p')"
        ).lastrowid
        camera_key = f"{site_id}:4"
        db.execute(
            """INSERT INTO cameras(camera_key,site_id,zm_id,name,rtsp_host,rtsp_enabled)
               VALUES(?,?,?,?,?,1)""",
            (camera_key, site_id, "4", "Tor", "zm"),
        )

    class DeniedResponse:
        status_code = 403

        def raise_for_status(self):
            raise core.requests.HTTPError(response=self)

    class Session:
        def put(self, _url, params=None, data=None, timeout=None):
            return DeniedResponse()

    monkeypatch.setattr(core, "_zone_minder_session", lambda _site: (Session(), {"token": "safe"}))
    try:
        core.reregister_monitor_rtsp(db_path, camera_key)
        assert False, "expected permission failure"
    except core.RtspReregisterError as error:
        assert error.stage == "disable"
        assert error.reason == "permission_denied"


def test_missing_rtsp_recovery_is_attempted_only_once_per_outage(monkeypatch):
    manager = core.PlayerManager("unused.db")
    calls = []
    monkeypatch.setattr(manager, "_recover_missing_rtsp", lambda player: calls.append(player.stream_key))

    class ImmediateThread:
        def __init__(self, target, args=(), daemon=None):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(core.threading, "Thread", ImmediateThread)
    player = core.Player(
        "stream", SimpleNamespace(stdout=None), "/tmp/missing.sock",
        tile_key="1:0", label="Tor", stream_key="1:4", failure_reason="rtsp-not-found",
    )
    manager._handle_player_failure(player)
    manager._handle_player_failure(player)
    assert calls == ["1:4"]
    assert manager.rtsp_recovery_status["1:4"]["state"] == "failed"


def test_player_output_detects_zoneminder_compact_404():
    player = core.Player(
        "stream",
        SimpleNamespace(stdout=io.StringIO("method DESCRIBE failed: 404Stream Not Found\n")),
        "/tmp/missing.sock",
    )
    core.PlayerManager._capture_player_output(player)
    assert player.failure_reason == "rtsp-not-found"


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
        assert "--hwdec=auto" in current.command
        assert upcoming is not None
        assert "/hof?" in upcoming.url
        assert upcoming.geometry == (0, 0, 1920, 1080)


def test_software_fallback_retries_stream_with_auto_copy(monkeypatch):
    class FakeProcess:
        pid = 42

        def poll(self):
            return None

    manager = core.PlayerManager("unused.db")
    manager.hwdec_strategies = ["auto", "auto-copy"]
    player = core.Player(
        "stream", FakeProcess(), "/tmp/retry.sock", stream_key="1:75",
        decode_strategy="auto",
    )

    def fake_ipc(_player, command):
        property_name = command[-1]
        if property_name == "video-params":
            return {"error": "success", "data": {"w": 640, "h": 360, "pixelformat": "yuv420p"}}
        if property_name == "video-frame-info":
            return {"error": "success", "data": {"picture-type": "P"}}
        if property_name == "track-list":
            return {"error": "success", "data": [{
                "type": "video", "selected": True, "codec": "h264", "codec-profile": "Baseline",
            }]}
        if property_name == "hwdec-current":
            return {"error": "success", "data": "no"}
        return {"error": "success", "data": "vaapi,vulkan"}

    monkeypatch.setattr(manager, "_ipc", fake_ipc)
    assert not manager._ready(player)
    assert manager.hwdec_preferences["1:75"] == "auto-copy"
    assert manager.reload_event.is_set()


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


def test_intel_legacy_driver_is_only_added_when_installed(tmp_path):
    hardware = {"cpu": "CPU", "gpu": "Intel HD Graphics 5500"}
    assert core.detect_hwdec_strategies(hardware, tmp_path) == [
        "auto", "auto-copy", "vaapi-copy-force-profile",
    ]
    driver = tmp_path / "x86_64-linux-gnu/dri/i965_drv_video.so"
    driver.parent.mkdir(parents=True)
    driver.touch()
    assert core.detect_hwdec_strategies(hardware, tmp_path) == [
        "auto", "auto-copy", "vaapi-copy-force-profile",
        "vaapi-i965", "vaapi-copy-i965",
    ]
    assert core.detect_hwdec_strategies({"gpu": "AMD Radeon"}, tmp_path) == [
        "auto", "auto-copy",
    ]


def test_failed_copy_advances_to_installed_intel_driver(monkeypatch):
    manager = core.PlayerManager("unused.db")
    manager.hwdec_strategies = [
        "auto", "auto-copy", "vaapi-copy-force-profile",
        "vaapi-i965", "vaapi-copy-i965",
    ]
    player = core.Player(
        "stream", SimpleNamespace(pid=43, poll=lambda: None), "/tmp/i965.sock",
        stream_key="1:88", decode_strategy="auto-copy",
    )

    def fake_ipc(_player, command):
        name = command[-1]
        values = {
            "video-params": {"w": 640, "h": 360},
            "video-frame-info": {"picture-type": "P"},
            "time-pos": 1.0,
            "hwdec-current": "no",
            "hwdec-interop": "none",
            "window-id": 1234,
            "track-list": [{"type": "video", "selected": True, "codec": "h264"}],
        }
        return {"error": "success", "data": values[name]}

    monkeypatch.setattr(manager, "_ipc", fake_ipc)
    assert not manager._ready(player)
    assert manager.hwdec_preferences["1:88"] == "vaapi-copy-force-profile"


def test_intel_h264_baseline_skips_redundant_auto_copy(monkeypatch):
    monkeypatch.setattr(
        core, "detect_decode_hardware",
        lambda: {"cpu": "Intel Core i5-2500", "gpu": "Intel 2nd Generation Graphics"},
    )
    manager = core.PlayerManager("unused.db")
    manager.hwdec_strategies = ["auto", "auto-copy", "vaapi-copy-force-profile"]
    player = core.Player(
        "stream", SimpleNamespace(pid=46, poll=lambda: None), "/tmp/baseline.sock",
        stream_key="1:107", decode_strategy="auto",
    )

    assert manager._next_hwdec_strategy(
        player, {"codec": "h264", "codec-profile": "Baseline"}
    ) == "vaapi-copy-force-profile"


def test_confirmed_hwdec_preference_is_persisted_per_gpu(monkeypatch, tmp_path):
    db_path = str(tmp_path / "preferences.db")
    init_db(db_path)
    monkeypatch.setattr(
        core, "detect_decode_hardware",
        lambda: {"cpu": "Intel Core i5-2500", "gpu": "Intel Sandy Bridge Graphics"},
    )
    first = core.PlayerManager(db_path)
    first.hwdec_strategies = ["auto", "vaapi-copy-force-profile"]
    first._remember_hwdec_preference("1:107", "vaapi-copy-force-profile")

    second = core.PlayerManager(db_path)

    assert second.hwdec_preferences["1:107"] == "vaapi-copy-force-profile"


def test_reconcile_limits_simultaneous_hwdec_upgrade_preloads(monkeypatch):
    class FakeProcess:
        def poll(self):
            return None

    manager = core.PlayerManager("unused.db")
    wanted = {}
    for index in range(3):
        key = f"1:{index}"
        stream_key = f"1:{100 + index}"
        manager.players[key] = core.Player(
            f"old-{index}", FakeProcess(), f"/tmp/old-{index}.sock",
            stream_key=stream_key, decode_strategy="auto",
        )
        wanted[key] = (
            core.StreamSpec(
                f"new-{index}", ["mpv"], "rtsp://test", stream_key=stream_key,
                decode_strategy="vaapi-copy-force-profile",
            ),
            None,
        )

    monkeypatch.setattr(manager, "desired", lambda: wanted)

    def fake_launch(key, spec, hidden):
        return core.Player(
            spec.signature, FakeProcess(), f"/tmp/{key}.sock",
            stream_key=spec.stream_key, decode_strategy=spec.decode_strategy,
        )

    monkeypatch.setattr(manager, "_launch", fake_launch)
    manager.reconcile()

    assert len(manager.preloads) == core.MAX_CONCURRENT_HWDEC_UPGRADES
    assert "1:2" not in manager.preloads


def test_stalled_hwdec_upgrade_keeps_visible_cpu_player(monkeypatch):
    class FakeProcess:
        def __init__(self):
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    manager = core.PlayerManager("unused.db")
    now = 100.0
    active = core.Player(
        "cpu", FakeProcess(), "/tmp/cpu.sock", stream_key="1:107",
        decode_strategy="auto", decode_device="cpu", hwdec="no",
    )
    preload = core.Player(
        "gpu", FakeProcess(), "/tmp/gpu.sock", stream_key="1:107",
        decode_strategy="vaapi-copy-force-profile", launched_at=now - 31,
    )
    manager.players["1:0"] = active
    manager.preloads["1:0"] = preload
    manager.hwdec_preferences["1:107"] = "vaapi-copy-force-profile"
    monkeypatch.setattr(core.time, "monotonic", lambda: now)
    monkeypatch.setattr(manager, "_ready", lambda _player: False)
    monkeypatch.setattr(
        manager, "desired",
        lambda: {"1:0": (
            core.StreamSpec(
                "gpu", ["mpv"], "rtsp://test", stream_key="1:107",
                decode_strategy="vaapi-copy-force-profile",
            ),
            None,
        )},
    )

    manager.reconcile()

    assert manager.players["1:0"] is active
    assert "1:0" not in manager.preloads
    assert preload.process.terminated
    assert manager.hwdec_preferences["1:107"] == "auto"


def test_stalled_remembered_hwdec_falls_back_to_explicit_cpu():
    player = core.Player(
        "gpu", SimpleNamespace(poll=lambda: None), "/tmp/gpu.sock",
        decode_strategy="vaapi-copy-force-profile", launched_at=10,
        decode_device="unknown",
    )

    assert core.PlayerManager._hwdec_start_timed_out(player, now=40)
    player.decode_device = "gpu"
    assert not core.PlayerManager._hwdec_start_timed_out(player, now=100)


def test_transient_unknown_hwdec_preserves_confirmed_gpu(monkeypatch):
    manager = core.PlayerManager("unused.db")
    manager.hwdec_strategies = [
        "auto", "auto-copy", "vaapi-copy-force-profile", "vaapi-i965",
    ]
    player = core.Player(
        "stream", SimpleNamespace(pid=44, poll=lambda: None), "/tmp/gpu.sock",
        stream_key="1:107", decode_strategy="vaapi-copy-force-profile",
        decode_device="gpu", hwdec="vaapi-copy",
    )

    def fake_ipc(_player, command):
        name = command[-1]
        values = {
            "video-params": {"w": 640, "h": 360, "pixelformat": "nv12"},
            "video-frame-info": {"picture-type": "P"},
            "time-pos": 1.0,
            "hwdec-current": "unknown",
            "hwdec-interop": "none",
            "window-id": 1234,
            "track-list": [],
        }
        return {"error": "success", "data": values[name]}

    monkeypatch.setattr(manager, "_ipc", fake_ipc)
    assert not manager._ready(player)
    assert player.decode_device == "gpu"
    assert player.hwdec == "vaapi-copy"
    assert manager.hwdec_preferences["1:107"] == "vaapi-copy-force-profile"
    assert not manager.reload_event.is_set()


def test_unknown_hwdec_is_not_misreported_as_cpu(monkeypatch):
    manager = core.PlayerManager("unused.db")
    manager.hwdec_strategies = ["auto", "auto-copy"]
    player = core.Player(
        "stream", SimpleNamespace(pid=45, poll=lambda: None), "/tmp/pending.sock",
        stream_key="1:108", decode_strategy="auto",
    )

    def fake_ipc(_player, command):
        name = command[-1]
        values = {
            "video-params": {"w": 640, "h": 360},
            "video-frame-info": {"picture-type": "P"},
            "time-pos": 1.0,
            "hwdec-current": "unknown",
            "hwdec-interop": "none",
            "window-id": 1234,
            "track-list": [],
        }
        return {"error": "success", "data": values[name]}

    monkeypatch.setattr(manager, "_ipc", fake_ipc)
    assert not manager._ready(player)
    assert player.decode_device == "unknown"
    assert player.hwdec == "unknown"
    assert "1:108" not in manager.hwdec_preferences
    assert not manager.reload_event.is_set()


def test_forced_profile_strategy_uses_vaapi_copy():
    assert core.hwdec_option("vaapi-copy-force-profile") == "vaapi-copy"
    assert core.hwdec_arguments("vaapi-copy-force-profile") == [
        "--hwdec=vaapi-copy", "--vd-lavc-check-hw-profile=no",
        "--hwdec-software-fallback=no",
    ]
    assert core.hwdec_arguments("auto") == ["--hwdec=auto"]


def test_runtime_applies_forced_profile_override_after_mpv_profile(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        db_path = str(Path(directory) / "forced-profile.db")
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
                ("1:107", site_id, "107", "Culinario", "10.0.0.2", 1, "107"),
            )
            screen_id = db.execute(
                "INSERT INTO screens(output_name,rows,cols) VALUES('HDMI-1',1,1)"
            ).lastrowid
            db.execute(
                """INSERT INTO tile_cameras(screen_id,position,camera_key,sort_order)
                   VALUES(?,?,?,?)""",
                (screen_id, 0, "1:107", 0),
            )

        monkeypatch.setattr(
            core,
            "detect_outputs",
            lambda: [{"name": "HDMI-1", "width": 1920, "height": 1080, "x": 0, "y": 0}],
        )
        manager = core.PlayerManager(db_path)
        manager.hwdec_preferences["1:107"] = "vaapi-copy-force-profile"
        spec, _ = manager.desired()[f"{screen_id}:0"]

        assert spec.command.index("--profile=low-latency") < spec.command.index(
            "--vd-lavc-check-hw-profile=no"
        )
        assert "--hwdec-software-fallback=no" in spec.command


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
        monkeypatch.setattr(
            core,
            "detect_network_status",
            lambda: {"state": "connected", "connections": [{"type": "ethernet", "interface": "enp1s0"}]},
        )
        manager = core.PlayerManager(db_path)
        manager.players[f"{screen_id}:0"] = core.Player(
            "gpu", FakeProcess(), "/tmp/gpu.sock", label="4K-Kamera",
            decode_device="gpu", hwdec="vaapi", codec="h264", stream_key="1:90",
        )
        manager.players[f"{screen_id}:1"] = core.Player(
            "cpu", FakeProcess(), "/tmp/cpu.sock", label="Substream",
            decode_device="cpu", hwdec="no", codec="h264", stream_key="1:75",
        )
        manager.preloads[f"{screen_id}:1"] = core.Player(
            "next", FakeProcess(), "/tmp/preload.sock", label="Nächste Kamera",
            decode_device="unknown", stream_key="1:88",
        )

        runtime = manager.runtime_status()
        status = runtime["screens"][str(screen_id)]
        assert runtime["network"]["connections"][0]["interface"] == "enp1s0"
        assert status["state"] == "mixed"
        assert status["label"] == "CPU + GPU · Intel HD Graphics 5500"
        assert {stream["device"] for stream in status["streams"]} == {"cpu", "gpu", "unknown"}
        assert {stream["camera_key"] for stream in status["streams"]} == {"1:90", "1:75", "1:88"}
        assert {stream["role"] for stream in status["streams"]} == {"active", "preload"}


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


def test_saved_layout_reset_discards_old_tile_images_before_relaunch(monkeypatch):
    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    manager = core.PlayerManager("unused.db")
    old_a = core.Player(
        "old-a", FakeProcess(101), "/tmp/old-a.sock",
        tile_key="1:0", stream_key="1:10",
    )
    old_b = core.Player(
        "old-b", FakeProcess(102), "/tmp/old-b.sock",
        tile_key="1:1", stream_key="1:11",
    )
    manager.players = {"1:0": old_a, "1:1": old_b}
    wanted = {
        "1:0": (core.StreamSpec("new-b", ["mpv"], "rtsp://b", stream_key="1:11"), None),
        "1:1": (core.StreamSpec("new-a", ["mpv"], "rtsp://a", stream_key="1:10"), None),
    }
    launched = []

    def fake_launch(key, spec, hidden):
        launched.append((key, spec.stream_key, hidden))
        return core.Player(
            spec.signature, FakeProcess(200 + len(launched)), f"/tmp/new-{len(launched)}.sock",
            tile_key=key, stream_key=spec.stream_key,
        )

    monkeypatch.setattr(manager, "desired", lambda: wanted)
    monkeypatch.setattr(manager, "_launch", fake_launch)
    monkeypatch.setattr(manager, "_ready", lambda _player: False)
    manager.request_reload(reset_layout=True)
    manager.reconcile()

    assert old_a.process.terminated
    assert old_b.process.terminated
    assert launched == [("1:0", "1:11", False), ("1:1", "1:10", False)]
    assert manager.players["1:0"].stream_key == "1:11"
    assert manager.players["1:1"].stream_key == "1:10"


def test_stale_stream_owner_cannot_remain_visible_on_another_tile(monkeypatch):
    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    manager = core.PlayerManager("unused.db")
    stale = core.Player(
        "old-a", FakeProcess(301), "/tmp/stale.sock",
        tile_key="1:0", stream_key="1:10",
    )
    manager.players["1:0"] = stale
    wanted = {
        "1:0": (core.StreamSpec("new-b", ["mpv"], "rtsp://b", stream_key="1:11"), None),
        "1:1": (core.StreamSpec("new-a", ["mpv"], "rtsp://a", stream_key="1:10"), None),
    }

    def fake_launch(key, spec, hidden):
        return core.Player(
            spec.signature, FakeProcess(400), "/tmp/new.sock",
            tile_key=key, stream_key=spec.stream_key,
        )

    monkeypatch.setattr(manager, "desired", lambda: wanted)
    monkeypatch.setattr(manager, "_launch", fake_launch)
    monkeypatch.setattr(manager, "_ready", lambda _player: False)
    manager.reconcile()

    assert stale.process.terminated
    owners = {player.stream_key: key for key, player in manager.players.items()}
    assert owners == {"1:11": "1:0", "1:10": "1:1"}


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


def test_stream_watchdog_detects_alive_player_without_playback_progress():
    player = core.Player(
        "stream", SimpleNamespace(poll=lambda: None), "/tmp/stalled.sock",
        launched_at=10.0, ready_since=11.0,
        last_playback_time=42.0, last_progress_at=20.0,
    )

    assert core.PlayerManager._stream_watchdog_reason(player, now=39.9) is None
    assert (
        core.PlayerManager._stream_watchdog_reason(player, now=40.0)
        == "playback-stalled"
    )


def test_stream_watchdog_detects_player_that_never_started():
    player = core.Player(
        "stream", SimpleNamespace(poll=lambda: None), "/tmp/not-started.sock",
        launched_at=10.0,
    )

    assert core.PlayerManager._stream_watchdog_reason(player, now=39.9) is None
    assert (
        core.PlayerManager._stream_watchdog_reason(player, now=40.0)
        == "startup-timeout"
    )


def test_ready_tracks_mpv_playback_progress(monkeypatch):
    manager = core.PlayerManager("unused.db")
    player = core.Player(
        "stream", SimpleNamespace(pid=500, poll=lambda: None), "/tmp/progress.sock",
        launched_at=5.0,
    )
    now = [10.0]
    position = [1.0]
    monkeypatch.setattr(core.time, "monotonic", lambda: now[0])

    def fake_ipc(_player, command):
        name = command[-1]
        values = {
            "video-params": {"w": 640, "h": 360},
            "video-frame-info": {"picture-type": "P"},
            "time-pos": position[0],
            "window-id": 1234,
            "hwdec-current": "no",
            "hwdec-interop": "none",
            "track-list": [{"type": "video", "selected": True, "codec": "h264"}],
        }
        return {"error": "success", "data": values[name]}

    monkeypatch.setattr(manager, "_ipc", fake_ipc)
    manager._ready(player)
    assert player.last_progress_at == 10.0

    now[0] = 15.0
    manager._ready(player)
    assert player.last_progress_at == 10.0

    now[0] = 16.0
    position[0] = 2.0
    manager._ready(player)
    assert player.last_progress_at == 16.0


def test_stream_watchdog_restarts_stalled_active_player(monkeypatch):
    class FakeProcess:
        pid = 501

        def __init__(self):
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    manager = core.PlayerManager("unused.db")
    stalled = core.Player(
        "stream", FakeProcess(), "/tmp/stalled-active.sock",
        tile_key="1:0", label="Kamera", stream_key="1:90",
        launched_at=10.0, ready_since=11.0,
        last_playback_time=42.0, last_progress_at=20.0,
    )
    manager.players["1:0"] = stalled
    spec = core.StreamSpec(
        "stream", ["mpv"], "rtsp://test", label="Kamera", stream_key="1:90",
    )
    replacement = core.Player(
        "stream", FakeProcess(), "/tmp/replacement.sock",
        tile_key="1:0", label="Kamera", stream_key="1:90", launched_at=40.0,
    )
    monkeypatch.setattr(core.time, "monotonic", lambda: 40.0)
    monkeypatch.setattr(manager, "desired", lambda: {"1:0": (spec, None)})
    monkeypatch.setattr(manager, "_ready", lambda _player: False)
    monkeypatch.setattr(manager, "_launch", lambda *_args, **_kwargs: replacement)

    manager.reconcile()

    assert stalled.process.terminated
    assert manager.players["1:0"] is replacement
    assert manager.reload_event.is_set()
