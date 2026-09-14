# Changelog

[Deutsch](CHANGELOG.md) · **English**

This changelog documents ZM Wall's features, operational flows, technical decisions, and fixes. The newest changes appear first. Versions before `0.3.0` were rapid beta checkpoints during development and were not published as separate GitHub Releases.

## Unreleased

- No changes yet.

## 0.3.0-beta.4 – 2026-09-14

### Added

- The live status below **Display active** now lists every active physical Ethernet and Wi-Fi connection with its interface name. Both paths are shown when wired and wireless networking are connected concurrently.
- Stream diagnostics now include the connection type, interface, IPv4 address, gateway, link speed, and default-route marker. For Wi-Fi, the report also includes SSID, signal strength, and TX bitrate when the system exposes them.
- Virtual networks such as Docker bridges are not reported as active device connections unless they own a default route.

### Tests

- Coverage for concurrent Ethernet/Wi-Fi, virtual-interface filtering, and formatted network details in the diagnostic report.

## 0.3.0-beta.3 – 2026-09-14

### Documentation

- Added a complete reverse-chronological changelog covering every versioned beta and the initial development phase.
- Features, operational flows, root causes, fixes, security decisions, tests, and reverted experiments are documented separately.
- German and English editions link to one another and are accessible from their respective README.

## 0.3.0-beta.2 – 2026-09-14

### Fixed

- After saving a changed layout, cameras could temporarily appear at both their former and new grid positions.
- The cause was the handoff logic intended for normal rotation: the old image remained visible until its replacement was ready, even when that camera had been moved to another tile.
- Layout changes, grid-size changes, and deleted displays now discard all players, preloads, and X11 surfaces belonging to the previous layout before the new assignments start.
- An additional runtime ownership check terminates a stale player as soon as the current configuration assigns the same stream to another tile.

### Flow

- **Save layout:** terminate all old players → remove old container surfaces → read and launch the new assignments.
- **Normal rotation:** continue showing the previous stream until the preloaded successor has stable frames, preserving seamless rotation.

### Tests

- Regression coverage for swapping two occupied grid positions.
- Regression coverage ensuring one runtime owner per stream.

## 0.3.0-beta.1 – 2026-09-12

### Added

- Complete German and English web interface.
- Header selector for **System language**, **Deutsch**, and **English**.
- The browser's preferred language is used by default; an explicit selection is stored for one year.
- Central dependency-free translations for templates, Flask messages, update states, and dynamic JavaScript labels.
- English documentation in `README.en.md` with reciprocal language links.
- Explicit documentation that ZM Wall uses ZoneMinder's integrated RTSP restream service and does not create additional direct camera connections.

### Changed

- Update, diagnostics, layout, ZoneMinder, and decoder messages follow the selected language.
- Camera search uses locale-aware lowercasing based on the active document language.

### Tests

- Matching key sets for German and English catalogs.
- Automatic language selection, manual override, and formatted message coverage.

## 0.3.0-beta – 2026-09-12

### Milestone

- First consolidated beta milestone with stable grid management, rotation without black transitions, stream preloading, automatic decoder selection, per-stream CPU/GPU status, web diagnostics, and confirmed web updates.
- Version line advanced from `0.2.0-beta.*` to `0.3.0-beta`.

## 0.2.0-beta.24 – 2026-09-12

### Fixed

- FFmpeg rejected some H.264 Baseline streams with `Codec h264 profile 66 not supported for hardware decode`, even though the Intel iHD driver could decode them.

### Changed

- After safe `auto` and `auto-copy` attempts, Intel systems receive a `vaapi-copy` fallback with FFmpeg's hardware-profile check disabled.
- This forced-profile path runs only on detected Intel hardware and only after normal methods fail.
- Legacy `i965` remains lower priority because diagnostics showed real reference-picture and slice errors.
- Decoder fallback remains isolated per stream and does not affect other cameras or hardware platforms.

## 0.2.0-beta.23 – 2026-09-12

### Added

- An isolated diagnostic pass using `--vd-lavc-check-hw-profile=no`.
- Side-by-side normal and disabled-profile tests for the system VAAPI driver and `i965`.

### Security

- The test disables software fallback, changes no camera setting, stores no decoder strategy, and redacts credentials and the complete RTSP URL.

## 0.2.0-beta.22 – 2026-09-12

### Added

- Protected diagnostics page in the web interface.
- Camera selection, progress state, sanitized output copy, and log download.
- Small diagnostics link directly below the displayed version.

### Flow

- Diagnostics open one additional read-only RTSP connection for 30 frames.
- Only one diagnostic can run at a time; normal display operation and saved configuration remain unchanged.

## 0.2.0-beta.21 – 2026-09-12

### Added

- `diagnose-stream.py` command-line tool for isolated hardware-decoder testing of a configured stream.
- System VAAPI and optional Intel `i965` tests without software fallback.
- Report includes system, ZM Wall and mpv versions, CPU, GPU, camera, decoder profile, and result code.

### Security

- The credential-bearing URL is passed to mpv via stdin and URL, username, and password are removed from output.

## 0.2.0-beta.20 – 2026-09-12

### Changed

- Every display card permanently shows the detected CPU and GPU model, independent of current decoder use.
- Actual decoder mode is shown per camera stream because one monitor can contain CPU and GPU streams simultaneously.
- States were clarified as `waiting`, `buffering`, `CPU · buffering`, `GPU · buffering`, `CPU`, and `GPU`.

### Flow

- `waiting` means no player and no additional decoder load exists for that camera.
- Preloading occurs only during the five-second lead window and is explicitly identified.

## 0.2.0-beta.19 – 2026-09-12

### Added

- Per-camera decoder badge in every grid assignment.
- Active cameras show `CPU` or `GPU`; inactive rotation entries show `waiting`.
- GPU tooltips include the detected model and active mpv hardware method.

## 0.2.0-beta.18 – 2026-09-12

### Added

- Hardware- and installed-driver-aware decoder chain instead of static Intel settings.
- Human-readable CPU and GPU model detection.
- Intel `i965` strategies are added only when the matching driver file exists.

### Decoder order

1. mpv `auto`
2. mpv `auto-copy`
3. installed hardware-specific fallbacks
4. reliable CPU decoding as the final fallback

### Fixed

- AMD, NVIDIA, and other platforms no longer receive Intel-specific VAAPI options.

## 0.2.0-beta.17 – 2026-09-12

### Changed

- `auto-copy` became a separate second launch attempt per stream.
- When the first frame reports software decoding, only that stream is rebuilt in the background.
- The current image remains visible until the copy attempt produces stable frames.
- Failed strategies are not retried endlessly during the same run.

## 0.2.0-beta.16 – 2026-09-12

### Added

- Live decoder status per physical monitor: CPU, GPU, mixed, detecting, or inactive.
- Human-readable hardware labels instead of cryptic PCI output.
- JSON runtime status endpoint for the web interface.

### Changed

- mpv first tries direct hardware decoding and then a compatible copy-back method; unsupported streams retain software fallback.

## 0.2.0-beta.15 – 2026-09-12

### Diagnostics

- First-frame logs now include camera, codec, profile, decoder, size, pixel format, hardware pixel format, `hwdec`, interop, launch time, and probe time.
- CPU-decoded streams can be identified without logging credentials.

## 0.2.0-beta.14 – 2026-09-12

### Added

- Persistent X11 container window outside Openbox management for each grid tile.
- Active and preloaded mpv instances render into separate child surfaces of the same container.

### Fixed

- Camera handoff occurs inside the X server and no longer switches independent top-level windows.
- Black transitions caused by slow Openbox activation were eliminated.

### Compatibility

- Top-level window control remains available if embedded X11 initialization fails.

## 0.2.0-beta.13 – 2026-09-12

### Diagnostics

- Millisecond timestamps for player launch, first frame, decoder, preload readiness, window raise, and predecessor termination.
- Camera credentials are excluded.

## 0.2.0-beta.12 – 2026-09-12

### Fixed

- Update controls remain visible in the header in every update state.
- Immediate manual update checks remain available when the installation is current.

## 0.2.0-beta.11 – 2026-09-12

### Added

- Web update checks every five minutes.
- Visible availability notice with explicit confirmation before installation.
- Progress/error states and automatic page reconnection after the short service restart.

### Flow and security

- Updates only from `noxare/ZMWall`, only on `main`, only without local tracked changes, and only by fast-forward.
- Only the ZM Wall web/player process restarts; the computer, Xorg, and LightDM keep running.
- Update output is written to `/var/lib/zmwall/update.log`.

## 0.2.0-beta.10 – 2026-09-12

### Added

- Safe `update.sh` for installed systems.
- Validation of root privileges, repository origin, branch, local state, and fast-forward eligibility.
- Python dependency refresh and controlled restart of the graphical ZM Wall session.

### Fixed

- Bootstrap procedure for installations that do not yet contain `update.sh`.
- Expected target-commit validation for web-triggered updates.
- Configuration, certificates, and database are preserved.

## 0.2.0-beta.9 – 2026-09-12

### Fixed

- Two consecutive one-second X11 activation timeouts caused an approximately two-second black image.
- The blocking activation call was removed and X11 commands were limited to 200 ms.
- Old and new windows overlap for 50 ms before the predecessor terminates.
- Preloads run only during the final five seconds rather than the entire interval.

## 0.2.0-beta.8 – 2026-09-12

### Reverted

- The forced OpenGL/VAAPI-copy renderer from Beta 7 was incompatible with the test hardware and could leave all video invisible.
- Forced renderer options were removed in favor of compatibility-first hardware selection.

## 0.2.0-beta.7 – 2026-09-12

### Experiment

- Intel X11 playback was temporarily forced through an OpenGL/VAAPI-copy path to require GPU decoding.
- Reverted in Beta 8 because it produced no visible video on the target system.

## 0.2.0-beta.6 – 2026-09-12

### Changed

- Preloaded windows are activated and raised before final handoff.
- If Openbox refuses activation, the predecessor loses topmost state and the new player is raised again.
- The previous player is always removed after a short presentation cycle so failed stacking cannot freeze rotation.

## 0.2.0-beta.5 – 2026-09-12

### Fixed

- Window raising can no longer block rotation indefinitely.
- `xdotool` calls received short timeouts and error paths.

## 0.2.0-beta.4 – 2026-09-12

### Experiment

- Introduced persistent double-buffered mpv windows for current and next cameras.
- Intended to provide instant switching by changing window stacking.

### Finding

- Permanent double buffering increased resource use and complexity. It was subsequently replaced by time-limited preloading and embedded X11 surfaces.

## 0.2.0-beta.3 – 2026-09-11

### Changed

- A preload is ready only after mpv reports video parameters and a decoded frame.
- The stream must deliver stable frames for at least 0.75 seconds.
- Frame loss restarts the stability timer, and the current image remains visible until the successor is proven ready.

## 0.2.0-beta.2 – 2026-09-11

### Added

- Hidden parallel launch of the next camera before rotation.
- Separate active and preload ownership per grid tile.

### Fixed

- Camera search now filters the pool by name, server, and ID and remains correct while cameras move.
- Installer added `xdotool` for the window handoff used at that time.

## 0.2.0-beta.1 – 2026-09-11

### Added

- Multiple cameras per tile with configurable rotation interval.
- Drag-and-drop camera pool; assigned cameras disappear from available entries.
- Movement between tiles, ordering within a tile, and tap-based touch operation.
- Automatic recovery for interrupted or temporarily unavailable RTSP streams.
- Database migration from one camera per tile to ordered multiple assignments.
- Server-side validation prevents one camera from being assigned to multiple positions.

### Flow

- The player manager derives the active camera from monotonic time, camera order, and rotation interval.
- Layout changes are stored atomically and applied without rebooting the complete system.

## Initial development phase – 2026-09-11

### Foundation

- Repository structure, MIT license, sample configuration, installer, uninstaller, Python application, and tests.
- Dedicated Debian display device using Xorg, Openbox, LightDM, mpv, and an automatically logged-in `zmwall` service user.
- Web UI for ZoneMinder connections, detected displays, grid dimensions, and camera assignment.
- SQLite storage for sites, ZoneMinder servers, cameras, displays, and grids.

### ZoneMinder and RTSP

- Synchronization through `/api/monitors.json` and `/api/servers.json`.
- Multi-server mapping using `Monitor.ServerId`, server hostname, and stored fallback IP.
- Flexible RTSP port, stream-name and URL rules plus per-camera overrides.
- Grid selection limited to cameras with ZoneMinder RTSP restream enabled.
- RTSP credentials are URL-encoded and the complete URL is passed to mpv through stdin instead of process arguments.

### Authentication

- The first local-admin-password design, confirmation check, and `pwreset.sh` were implemented and then removed completely.
- Current flow established during this phase: initial setup stays open until the first successful ZoneMinder sync; afterwards HTTP Basic credentials are verified directly against `/api/host/login.json`.
- With multiple ZoneMinder connections, a valid user from any successfully synchronized installation grants access.

### Display placement

- Exact, gap-free division of every XRandR output into grid cells, including remainder pixels and negative monitor coordinates.
- mpv binds to the configured physical output and can stretch video to fill its complete cell.
- Several early positioning methods were consolidated after competing mechanisms could place windows outside their assigned cells.
- `Ctrl+Alt+End` exits the Openbox session and the final tile shows a subtle shortcut hint.

### HTTPS

- Nginx frontend on port 443 with HTTP-to-HTTPS redirection.
- Local ten-year ZM Wall CA and automatically renewed 90-day server certificate.
- Daily systemd timer renews 30 days before expiry and when local IPv4 addresses change.
- Installer/uninstaller conflict with the default Nginx site was fixed.

## Maintaining this changelog

- Add new entries above older versions using the next version number.
- Classify relevant work as **Added**, **Changed**, **Fixed**, **Flow**, **Security**, **Diagnostics**, **Tests**, or **Reverted**.
- Keep failed experiments when they explain later architectural decisions.
