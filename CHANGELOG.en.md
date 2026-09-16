# Changelog

[Deutsch](CHANGELOG.md) · **English**

This changelog documents ZM Wall's features, operational flows, technical decisions, and fixes. The newest changes appear first. Versions before `0.3.0` were rapid beta checkpoints during development and were not published as separate GitHub Releases.

## Unreleased

- No changes yet.

## 0.3.0-beta.21 – 2026-09-16

- Adding a display now offers compact visual grid presets for `2×2`, `3×2`, `3×3`, `4×3`, and `4×4`, plus a custom size.
- Existing displays show only a subtle grid control. The symbolic preset picker opens on demand, while numeric fields appear exclusively under **Custom**.
- The visible configuration responds immediately to a new grid size but remains unsaved until **Apply all layouts** is selected.
- When shrinking a grid would remove occupied positions, ZM Wall warns first and returns their cameras to the available camera list after confirmation.

## 0.3.0-beta.20 – 2026-09-16

- Decoder selection now has a Rockchip backend. On detected Rockchip hardware, `rkmpp` is placed before the existing safe `auto`/`auto-copy` path only when the installed mpv build actually advertises that decoder. Existing Intel and AMD systems retain their previous ordering.
- The active video backend is shown for every configured display.
- Configured monitor connectors are no longer offered under **Add display**. Deleting a display makes its connector selectable again, while duplicate definitions are also rejected server-side.
- Regression coverage for conditional Rockchip selection and unique monitor assignment.

## 0.3.0-beta.19 – 2026-09-15

- Batch diagnostics now update each camera's visible stream status immediately after its probe instead of waiting for all cameras to finish.
- **Retry RTSP repair** is now also offered when the stream probe reports **stream not found**, even if no watchdog recovery event exists yet.
- Regression coverage for the repair action without a previous watchdog event. A total of 64 automated tests.

## 0.3.0-beta.18 – 2026-09-15

### Diagnostic admin mode

- A successfully used temporary ZoneMinder API user remains active for further RTSP repairs and resolution updates in the same diagnostic session.
- The active user is shown on the diagnostics page, so credentials no longer need to be entered for every camera.
- The password exists only in memory of the running ZM Wall process. Credentials are not placed in cookies, the database, or logs.
- Returning to the main page immediately clears the username and password. Rejected credentials (`HTTP 401`) are not retained and are removed from an active diagnostic session.

### Tests

- Regression coverage for reusing and clearing temporary API credentials. A total of 63 automated tests.

## 0.3.0-beta.17 – 2026-09-15

### Interface

- The diagnostics page now uses the full available window width. Table contents can wrap and action buttons use a compact layout, keeping the right half accessible at common desktop resolutions without hidden horizontal navigation.
- The concrete cause of a failed RTSP repair is shown directly below its state instead of only in a tooltip.
- Failed repairs can be repeated from the same camera row with **Retry RTSP repair**.

### One-time API login

- A different authorized ZoneMinder user can be supplied once for a manual RTSP re-registration or confirmed resolution update.
- These credentials apply only to the selected API request. They are neither stored in the ZM Wall database nor written to diagnostic or application logs.
- Username and password must be supplied together; incomplete input is rejected before an API request.

### Tests

- Regression coverage for one-time credentials during resolution updates and manual RTSP repair. 62 automated tests in total.

## 0.3.0-beta.16 – 2026-09-15

### Diagnostics

- The latest automatic RTSP repair attempt is persisted with state, phase, credential-safe reason, and timestamp and is displayed on the diagnostics page.
- API login, disable, enable, restoration, and verification are reported as distinct phases.
- HTTP 401 is identified as rejected authentication, while HTTP 403 explicitly indicates that the configured ZoneMinder user lacks edit permission. Other HTTP status codes are shown without a URL, token, or credentials.
- A successful API re-registration followed by another RTSP 404 is distinguished from an API call that failed.
- The stream badge tooltip contains the same concrete reason as the diagnostics page.

### Tests

- Regression coverage for a ZoneMinder write request rejected with HTTP 403 while retaining complete once-per-outage and API verification coverage.

## 0.3.0-beta.15 – 2026-09-15

### Added

- Running mpv processes are monitored for ZoneMinder's explicit `404 Stream Not Found` response without logging RTSP addresses or credentials.
- On the first occurrence per outage, ZM Wall re-registers the affected restream through `Monitor[RTSPServer]=0/1`, verifies the API state, and retries only that stream.
- The stream badge reports “repairing RTSP”, “retrying RTSP”, or “RTSP unavailable” during this process.

### Safety and flow

- Recovery runs outside the display loop and does not block other streams or camera rotation.
- Network, authentication, and decoder failures never trigger a write API action.
- The API repair is not repeated until a new video frame has been received. After successful recovery, one attempt is available again for a later, separate outage.
- If a failure occurs after disabling the restream, ZM Wall makes a best-effort call to enable it again.

### Tests

- Regression coverage for 404 detection, the verified API toggle, and the once-per-outage guard.

## 0.3.0-beta.14 – 2026-09-15

### Fixed

- ZoneMinder/FFmpeg's compact `404Stream Not Found` message is now classified as a missing RTSP stream just like `404 Not Found`, rather than only producing a generic mpv exit-code interpretation.

### Diagnostics

- The single-stream report now includes ZoneMinder status, `ServerId`, readable server name, the API's RTSP-enabled state, and the source of the selected stream name. Incorrect multi-server mappings, stream overrides, and unavailable restreams can therefore be traced in one report.

### Tests

- Regression coverage for the observed ZoneMinder message `DESCRIBE failed: 404Stream Not Found`.

## 0.3.0-beta.13 – 2026-09-15

### Fixed

- The detailed per-stream GPU test used `all=no`, suppressing all general mpv, RTSP, and demuxer messages. If a stream failed before the video decoder opened, the report therefore contained only “mpv produced no decoder diagnostic” and exit code 2.
- General connection and input messages now remain visible while decoder details continue to use an increased log level.

### Diagnostics

- Every driver variant receives a short interpretation such as authentication rejected, stream not found, connection failed, hardware profile rejected, resolution limit, or successfully initialized GPU decoding.
- The report identifies the RTSP host, port, stream path, and TCP transport without including a username, password, or URL parameters.
- URL-encoded forms of usernames and passwords are removed from mpv output as well.

### Tests

- Regression coverage for visible general mpv messages, failure interpretation, and URL-encoded credentials.

## 0.3.0-beta.12 – 2026-09-15

### Fixed

- The all-camera diagnostic previously combined resolution comparison, reachability, and hardware-decoder outcome into one status. An earlier VAAPI rejection or exhausted GPU could therefore appear as a red “GPU limit” next to a resolution that actually matched.
- The batch probe now reads metadata sequentially using software decoding. GPU suitability is assessed only by the detailed single-stream test or the decoder actually used by the running player.
- Failed probes retain the last reliable stream metadata and store a separate probe state with a distinct reason such as timeout, authentication, connection, missing stream, or decoder failure.
- `0.000000 fps` is no longer presented as a real frame rate.
- The TSV export keeps multiline camera fields on one record and omits action-button text.

### Added

- ZoneMinder status, RTSP probe status, and resolution comparison now have separate columns in the all-camera overview.
- Each camera can be sent directly from the overview to the detailed GPU diagnostic.
- When a successful stream probe proves a resolution mismatch, `Monitor.Width`/`Monitor.Height` can be corrected through the ZoneMinder API after explicit confirmation. ZM Wall reads the monitor back and updates its local value only after successful verification.
- Existing databases are migrated without data loss to separate probe-state and metadata fields.

### Security

- Normal ZoneMinder synchronization never changes resolutions automatically. API errors shown in the web interface do not expose authentication tokens.

### Tests

- Regression coverage for separated diagnostic states, unknown zero FPS, failure classification, database migration, and the verified ZoneMinder write path.

## 0.3.0-beta.11 – 2026-09-15

### Fixed

- The previous stream watchdog restarted mpv only after the process exited completely. Following an RTSP loss, mpv could remain alive without receiving new frames and was therefore incorrectly treated as active.
- ZM Wall now also monitors mpv playback-time progress. If a previously running stream remains stalled for 20 seconds, only the affected player is rebuilt.
- A player that never produces its first frame within 30 seconds is also replaced cleanly. This applies to preloaded rotation streams as well.
- The existing GPU-capacity fallback retains priority, preventing an exhausted GPU from being loaded by endless hardware restart attempts.

### Diagnostics

- Watchdog restarts are logged as `stream-watchdog-restart` with role, reason, stall duration, and process ID.

### Tests

- Regression coverage for stalled playback progress, missing stream startup, progress tracking, and targeted replacement of a still-running mpv process.

## 0.3.0-beta.10 – 2026-09-14

### Fixed

- The all-camera diagnostic could incorrectly report a GPU resolution limit when mpv first rejected one unsuitable hardware path and subsequently used another hardware decoder successfully.
- A later confirmed GPU success now takes precedence over an earlier image-size rejection. Red is shown only when the size rejection remains the final relevant hardware result.

### Tests

- Regression coverage for a matching 720×576 stream whose first hardware path is rejected before a later hardware decoder succeeds.

## 0.3.0-beta.9 – 2026-09-14

### Added

- The diagnostics page now provides an asynchronous all-camera diagnostic in addition to the detailed single-stream test.
- At most two short, read-only stream probes run concurrently. Progress and persisted results remain visible in the web interface, and the summary can be downloaded as a TSV file.
- The all-camera diagnostic compares the ZoneMinder monitor resolution with the resolution actually found in the restream and records codec, profile, and frame rate.
- Every camera in the grid configuration receives a subtle resolution badge. Green means the resolutions match, yellow indicates a mismatch, red identifies an explicit GPU image-size rejection, and gray marks an unchecked stream.
- A compact legend is shown next to each display's hardware details.

### Flow and diagnostics

- Stream metadata already observed by the regular player is cached without opening another connection. The all-camera diagnostic can then refresh the complete inventory on demand.
- RTSP addresses and credentials are never included in persisted results or the downloadable summary.

### Tests

- Coverage for the low-impact single-frame probe, explicit GPU resolution-limit detection, and resolution data rendering on both the configuration and diagnostics pages.

## 0.3.0-beta.8 – 2026-09-14

### Fixed

- When an older GPU reached its practical concurrent decoder limit, a forced VAAPI player could previously remain indefinitely without a stable frame and appeared only as `…` in the web interface.
- A hardware upgrade is now stopped cleanly after 30 seconds without confirmed GPU decoding. An existing visible CPU player remains active without a visual interruption; after a direct start with a remembered GPU strategy, an explicit software decoder is started instead.
- Capacity-dependent CPU fallbacks are not persisted, allowing the stream to try the GPU again with a smaller layout or on different hardware.

### Tests

- Coverage for GPU-upgrade timeout, retaining the visible CPU player, and explicit software fallback after a blocked remembered hardware start.

## 0.3.0-beta.7 – 2026-09-14

### Improved

- Intel H.264 Baseline streams skip the already ineffective `auto-copy` intermediate attempt after an explicit CPU result and proceed directly to the confirmed VAAPI compatibility strategy.
- At most two decoder upgrades are preloaded concurrently. A large grid therefore no longer creates a replacement process for every position at once and overloads older CPUs and GPUs during automatic detection.
- Successful decoder strategies are persisted in the local database per stream and GPU model. After a ZM Wall update or restart, a known stream starts directly with its last confirmed hardware configuration.

### Tests

- Coverage for the shortened Intel Baseline chain, hardware-specific persistence, and the concurrent decoder-upgrade limit.

## 0.3.0-beta.6 – 2026-09-14

### Fixed

- A transient IPC timeout returned `unknown` for `hwdec-current`. This was incorrectly treated as CPU decoding, causing an already confirmed `vaapi-copy` player to be discarded and the decoder chain to advance unnecessarily.
- Confirmed GPU decoding is now preserved when a status query is temporarily unknown. Only mpv's explicit `hwdec=no` response may trigger another decoder attempt.
- An unknown decoder state is no longer misleadingly displayed as CPU in the web interface.

### Diagnostics and tests

- First-frame events now log the retained effective decoder separately from the status currently reported by mpv.
- Regression coverage now includes preserving a confirmed GPU and handling a still-unknown decoder state.

## 0.3.0-beta.5 – 2026-09-14

### Fixed

- Stream diagnostics could render affected Intel streams through `vaapi-copy`, while the regular player silently returned to CPU decoding after individual malformed reference pictures. The confirmed VAAPI compatibility strategy now disables that automatic software fallback as well.
- Affected H.264 streams with contradictory profile metadata therefore remain on the GPU during normal wall operation. Regular streams and other hardware retain their existing safe fallback chain.

### Tests

- Regression tests ensure that the compatibility options use their final effective order and that this targeted mode no longer permits a silent CPU fallback.

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
