# ZM Wall

[Deutsch](README.md) · **English**

[Detailed changelog](CHANGELOG.en.md)

Current development version: **0.3.0-beta.24**

ZM Wall turns a lightweight Debian device into a network-managed RTSP video wall for ZoneMinder. Each physical display can use its own grid and camera assignment. ZM Wall uses ZoneMinder's integrated RTSP restream feature: it does not open another direct connection to each camera. Instead, the streams already provided by ZoneMinder are rendered with `mpv`, while the web interface is used for administration.

## Features

- configurable 1×1 to 8×8 grid for each display output
- any number of connected displays
- multiple independent ZoneMinder connections
- ZoneMinder multi-server mapping through `Monitor.ServerId` and `/api/servers.json`
- automatic import of camera ID, name, status, and responsible server
- live Ethernet/Wi-Fi connection status with network details in diagnostics
- preferred hostnames with an automatic fallback IP for each ZoneMinder server
- automatic API synchronization every five minutes and manual synchronization
- automatic recovery of interrupted or temporarily unavailable streams
- drag-and-drop assignment from a pool of unassigned RTSP cameras
- multiple cameras per grid position with a configurable rotation interval
- preloaded camera rotation without an intentionally introduced black frame
- configurable RTSP port, stream-name rule, and URL template
- optional RTSP host or stream-name override per camera
- initial web configuration without a separate local password
- authentication directly against ZoneMinder after the first successful synchronization
- playback of ZoneMinder's integrated RTSP restreams through `mpv`, hardware decoding, and TCP transport
- German and English web UI, selected automatically from the browser/system language and always manually switchable
- all-camera RTSP diagnostics comparing the ZoneMinder configuration with the actual stream resolution
- subtle color-coded resolution badges for every camera in the grid configuration
- web-based stream diagnostics with credential redaction
- safe updates from the web interface without rebooting the complete client

## Requirements

- Debian 12 or 13 on a dedicated display device
- network access to the ZoneMinder API and all required RTSP ports
- a dedicated ZoneMinder user with at least read access to the required monitors
- resolvable ZoneMinder server hostnames for automatic multi-server mapping

Enable the ZoneMinder API under **Options → System → OPT_USE_API**. Current token authentication also requires `AUTH_HASH_SECRET` to be configured.

ZoneMinder's RTSP restream service must be reachable for the selected monitors. Its default port is `20000`. ZM Wall reuses these existing ZoneMinder streams and therefore does not create additional direct camera connections.

## Installation

Run the following commands on a fresh Debian installation:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/noxare/ZMWall.git
cd ZMWall
sudo bash install.sh
sudo reboot
```

The installer configures Xorg, Openbox, LightDM, `mpv`, Nginx, local HTTPS, the `zmwall` user, and the Python environment. It does not create a separate password for the ZM Wall web interface. After rebooting, open:

```text
https://DISPLAY-DEVICE-IP
```

## Local HTTPS

Nginx serves the web interface on port 443 and redirects port 80 to HTTPS. The Python web service only listens locally on `127.0.0.1:8080`.

The installer creates a local ZM Wall CA valid for ten years. Its server certificate is valid for 90 days. The `zmwall-cert-renew.timer` systemd timer checks it daily, renews it 30 days before expiry, and accounts for changed local IPv4 addresses.

Download the public CA after installation and trust it once on each administration device:

```text
https://DISPLAY-DEVICE-IP/zmwall-local-ca.crt
```

The private CA key remains in `/etc/zmwall/tls/zmwall-local-ca.key` and must never leave the display device.

## Initial configuration and login

The web interface intentionally remains open until at least one ZoneMinder connection has synchronized successfully. This allows the first connection to be configured and incorrect URLs, TLS settings, or credentials to be corrected.

1. Add a ZoneMinder connection in the web interface. Enter a URL such as `https://zm.example/zm`, meaning the path before `/api`.
2. Enter a ZoneMinder username and password for the API and RTSP connection.
3. Set the RTSP port. The default is `20000`.
4. Set the stream-name rule. For example, `{id}` produces stream name `100` for monitor 100.
5. After the first successful synchronization, the web interface is protected automatically. The browser requests credentials, which are verified directly against `/api/host/login.json` on the detected ZoneMinder server.
6. Add a detected display output and select its rows, columns, and rotation interval.
7. Drag cameras from **Available cameras** into grid positions. On touch devices, tap the camera first and then the target position.
8. Multiple cameras in the same position rotate in their displayed order. They can be moved between positions or returned to the pool with **×**.
9. Select **Apply all layouts**. The display is rebuilt without rebooting the device.

When multiple independent ZoneMinder connections have synchronized successfully, valid credentials from any one of them grant access to ZM Wall.

The default RTSP URL template is:

```text
rtsp://{host}:{port}/{stream}?username={username}&password={password}
```

Available URL values are `{host}`, `{port}`, `{stream}`, `{username}`, `{password}`, `{id}`, and `{name}`. The stream-name rule supports `{id}`, `{name}`, and `{server_id}`.

## Language selection

Without a saved choice, ZM Wall follows the language preference sent by the browser, which normally follows the operating-system language. Use the language selector in the header to choose **Deutsch**, **English**, or return to **System language**. The explicit choice is stored in the browser.

## Multi-server behavior

ZM Wall requests `/api/monitors.json` and `/api/servers.json` from the configured ZoneMinder controller. Each camera's `Monitor.ServerId` is matched to `Server.Id`, and `Server.Hostname` becomes its RTSP host. A single-server installation uses the hostname from the configured ZoneMinder URL.

Each successful name lookup also stores the resolved IPv4 address. If the hostname later becomes unavailable, ZM Wall automatically uses that last known address. If the hostname cannot be resolved during initial setup, a **Fallback IP** can be assigned once for that ZoneMinder server and applies to all cameras with the same `ServerId`.

For special cases, an individual **RTSP host (optional)** can still be configured for a camera. This per-camera override has the highest priority and survives later synchronizations.

## Stream recovery, rotation, and decoding

ZM Wall monitors every started `mpv` process. If an RTSP stream ends or reaches the network read timeout, the player is terminated and restarted at short intervals. The image returns automatically as soon as the camera and RTSP server are available again; no wall restart is required.

If a reachable ZoneMinder RTSP server explicitly responds with `404 Stream Not Found`, ZM Wall reports the condition on the affected stream. Once per outage, it toggles `Monitor.RTSPServer` off and on through the ZoneMinder API, verifies that it is enabled, and retries the stream. The one-attempt guard is reset only after a video frame is received again. Network, authentication, and decoder failures never change a ZoneMinder setting.

For rotating positions, the next stream starts in parallel in a hidden surface five seconds before the switch. It must render real video frames and remain stable for at least 0.75 seconds. The previous image remains visible until the new stream is ready. Permanent X11 container windows and separate child surfaces make the final switch within the X server, avoiding the former black interval between top-level windows.

When a changed layout is saved, ZM Wall discards all players and preload surfaces belonging to the previous layout before starting the new assignments. This prevents a moved camera from remaining visible at both its former and new grid positions. A runtime ownership check additionally removes stale players if their stream now belongs to another tile. Seamless preloading for normal camera rotation remains active.

Decoder selection is performed per stream. ZM Wall tries safe automatic hardware decoding first, then compatible copy-back strategies, hardware-specific fallbacks detected on the device, and finally CPU decoding. The web interface displays the detected CPU and GPU model for every monitor and the active `CPU`, `GPU`, `waiting`, or `buffering` state for every assigned stream.

On Intel systems, ZM Wall can use a confirmed VAAPI copy-back fallback with the FFmpeg hardware-profile check disabled when normal methods reject a stream despite driver support. The web diagnostics page tests this condition without changing the camera or stored decoder strategy.

## Operation and diagnostics

The area below **Display active** shows the display device's current network paths live. When Ethernet and Wi-Fi are connected at the same time, both interfaces are listed. Stream diagnostics add the IPv4 address, gateway, link speed, default route, and—when available—Wi-Fi SSID, signal strength, and TX bitrate. Virtual Docker interfaces without a default route are hidden.

In addition to a detailed per-stream GPU test, the diagnostics page provides **Test all cameras**. This all-camera diagnostic inspects the restreams delivered by ZoneMinder sequentially and without a hardware decoder. Reachability, ZoneMinder status, stream metadata, and the resolution comparison are displayed separately. An exhausted or incompatible GPU can therefore no longer appear as a supposed resolution error. The TSV summary excludes RTSP addresses, credentials, and action-button text.

When a successfully probed stream resolution differs from `Monitor.Width` and `Monitor.Height`, the detected dimensions can be explicitly confirmed for that camera and applied through the ZoneMinder API. ZM Wall reads the monitor back and updates its local configuration only after ZoneMinder verifies the change. Normal synchronization deliberately performs no automatic bulk edits; the configured ZoneMinder user needs edit permission for this action.

Important paths:

```text
/opt/zmwall/                       application
/etc/zmwall.env                    runtime configuration
/var/lib/zmwall/zmwall.db          ZoneMinder, camera, and grid configuration
/var/lib/zmwall/zmwall.log         application and player log
/var/lib/zmwall/update.log         update log
/etc/lightdm/lightdm.conf.d/50-zmwall.conf
```

Check detected displays:

```bash
sudo -u zmwall DISPLAY=:0 xrandr --query
```

Follow the log:

```bash
sudo tail -f /var/lib/zmwall/zmwall.log
```

The **Open diagnostics** link below the version opens the protected stream diagnostics page. Select a camera to test its original ZoneMinder RTSP stream against the available VAAPI strategies. The generated report removes the RTSP URL, username, and password and can be copied or downloaded.

## Updates

Update an installed ZM Wall directly from the official Git repository:

```bash
sudo /opt/zmwall/update.sh
```

When upgrading for the first time from an older version that does not contain `update.sh`:

```bash
cd /opt/zmwall
sudo -u zmwall git pull --ff-only origin main
sudo ./update.sh
```

The script validates the repository and branch, only accepts fast-forward updates from `noxare/ZMWall`, updates Python dependencies, and restarts the graphical ZM Wall process. `/etc/zmwall.env`, certificates, and `/var/lib/zmwall/zmwall.db` are preserved. Local modifications to tracked application files stop the update instead of being overwritten.

The update control in the header checks for new commits every five minutes and also supports an immediate manual check. An update only starts after confirmation. It restarts the ZM Wall web/player process through the existing Openbox watchdog; the computer, LightDM, and Xorg are not rebooted.

## Security

- Initial configuration is open only until the first ZoneMinder connection synchronizes successfully. ZM Wall should still be used only inside a trusted LAN or administration VLAN.
- Afterwards, HTTP Basic authentication is required for every request, and the submitted credentials are checked directly against ZoneMinder. There is no separate local web password.
- Basic authentication is transmitted only inside the local HTTPS connection.
- ZoneMinder API and RTSP credentials are stored locally in `/var/lib/zmwall/zmwall.db`, accessible only to the service user.
- The credential-bearing RTSP URL is passed to `mpv` through standard input and therefore does not appear in its process arguments.
- A dedicated ZoneMinder user limited to the cameras being displayed is recommended.

## Uninstallation

```bash
sudo bash /opt/zmwall/uninstall.sh
```

Uninstallation removes the application and autostart configuration but keeps `/var/lib/zmwall` as a backup.
