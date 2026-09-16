# ZM Wall

[Deutsch](README.md) · **English**

[Detailed changelog](CHANGELOG.en.md)

Current development version: **0.3.0-beta.24**

ZM Wall turns a Debian device into a network-managed RTSP video wall for ZoneMinder. Each physical display has its own grid and camera assignment. Playback uses ZoneMinder's integrated RTSP restreams and creates no additional direct camera connections.

## Current features

- multiple displays and independent ZoneMinder connections
- visual grid presets and custom grids from 1×1 to 8×8
- drag-and-drop assignment from a pool of available RTSP cameras
- multiple cameras per grid position with a configurable rotation interval
- preloaded camera rotation without an intentionally introduced black interval
- automatic recovery of unavailable streams
- automatic ZoneMinder multi-server mapping through `Monitor.ServerId`
- configurable RTSP ports, stream names, and URL templates
- automatic hardware decoder selection with Rockchip MPP and Intel VAAPI support plus CPU fallback
- live CPU/GPU decoder state for every stream
- fullscreen view of a grid position by double-click or keyboard shortcut
- German and English web interface and wall hints
- stream, resolution, hardware decoder, and network diagnostics
- protected updates directly from the web interface

## Requirements

- Debian 12 or 13 on a dedicated display device
- network access to the ZoneMinder API and RTSP restreams
- a ZoneMinder user with read access to the required monitors
- API enabled under **Options → System → OPT_USE_API**
- `AUTH_HASH_SECRET` configured for token authentication
- reachable RTSP restream service; the default port is `20000`

For automatic multi-server mapping, the display device should be able to resolve the server hostnames stored in ZoneMinder. A fallback IP can be configured for each server if required.

## Installation

Run on a fresh Debian installation:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/noxare/ZMWall.git
cd ZMWall
sudo bash install.sh
sudo reboot
```

The installer configures Xorg, Openbox, LightDM, `mpv`, Nginx, local HTTPS, the `zmwall` user, and the Python environment. After rebooting, open:

```text
https://DISPLAY-DEVICE-IP
```

## Initial configuration

The web interface remains open until the first ZoneMinder connection synchronizes successfully.

1. Add a ZoneMinder connection, for example `https://zm.example/zm` without `/api`.
2. Enter the ZoneMinder username, password, and RTSP port.
3. Configure the stream-name rule; `{id}` uses the monitor ID.
4. Synchronize the connection. The web interface is then protected automatically by authentication against ZoneMinder.
5. Add a detected display output and select its grid and rotation interval.
6. Drag cameras from **Available cameras** into grid positions.
7. Select **Apply all layouts**.

Multiple cameras in one position rotate in their displayed order. On touch devices, tap the camera and then its target position. A configured display output becomes selectable again only after its configuration has been deleted.

The default RTSP template is:

```text
rtsp://{host}:{port}/{stream}?username={username}&password={password}
```

Available values are `{host}`, `{port}`, `{stream}`, `{username}`, `{password}`, `{id}`, and `{name}`. The stream-name rule supports `{id}`, `{name}`, and `{server_id}`.

## Wall controls

- **Double-click a camera image:** show or close that grid position in fullscreen on its physical display
- **Esc:** close fullscreen
- **Hold Alt, type the field number, release Alt:** open or close the numbered grid position in fullscreen
- **Ctrl+Alt+End:** end the local Openbox session

The field number appears subtly in the upper-left corner of the camera image. Camera rotation pauses for a fullscreen position, while its running streams remain available for a fast return to the grid.

## Multi-server operation and stream recovery

ZM Wall maps `Monitor.ServerId` to `/api/servers.json` and uses the corresponding server hostname as the RTSP target. The last successfully resolved IPv4 address is stored as an automatic fallback. A fallback IP per server and an individual RTSP host or stream name per camera can also be configured.

Interrupted or temporarily unavailable streams restart automatically. If a reachable ZoneMinder restream explicitly returns `404 Stream Not Found`, ZM Wall can repair that monitor's RTSP registration through the ZoneMinder API. Network, authentication, and decoder failures never change a ZoneMinder setting.

## Diagnostics and operation

The diagnostics page provides:

- individual stream and hardware decoder tests
- sequential testing of all enabled cameras
- comparison of the actual stream resolution with the ZoneMinder configuration
- controlled application of a confirmed resolution to ZoneMinder
- RTSP re-registration with temporary authorized credentials
- Ethernet/Wi-Fi status, IPv4 address, gateway, link speed, and Wi-Fi details
- sanitized reports without RTSP addresses or credentials

Important paths:

```text
/opt/zmwall/                       application
/etc/zmwall.env                    runtime configuration
/var/lib/zmwall/zmwall.db          configuration and layouts
/var/lib/zmwall/zmwall.log         application and player log
/var/lib/zmwall/update.log         update log
```

Check detected displays:

```bash
sudo -u zmwall DISPLAY=:0 xrandr --query
```

Follow the log:

```bash
sudo tail -f /var/lib/zmwall/zmwall.log
```

## Local HTTPS

Nginx serves the web interface on port 443; the Python web service remains limited to `127.0.0.1:8080`. The installer creates a local CA and an automatically renewed server certificate. Trust the public CA once on each administration device:

```text
https://DISPLAY-DEVICE-IP/zmwall-local-ca.crt
```

The private CA key at `/etc/zmwall/tls/zmwall-local-ca.key` must never leave the display device.

## Updates

Use the header control to check for updates and install an available fast-forward update. Alternatively:

```bash
sudo /opt/zmwall/update.sh
```

Configuration, database, and certificates are preserved. Local changes to managed application files stop the update instead of being overwritten.

## Security

- Run ZM Wall only inside a trusted LAN or administration VLAN.
- After the first synchronization, credentials are verified directly against ZoneMinder; there is no separate web password.
- API and RTSP credentials are protected in `/var/lib/zmwall/zmwall.db`.
- Credential-bearing RTSP URLs do not appear in process arguments or diagnostic reports.
- A dedicated ZoneMinder user with the minimum required permissions is recommended.

## Uninstallation

```bash
sudo bash /opt/zmwall/uninstall.sh
```

Uninstallation removes the application and autostart configuration but retains `/var/lib/zmwall` as a backup.
