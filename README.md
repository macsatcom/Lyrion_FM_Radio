# Lyrion_FM_Radio
Stream FM radio to Lyrion Music Server, inclusive the option to change frequency

FM Radio reception via RTL-SDR for Lyrion Music Server (LMS).

Receives FM radio using an RTL-SDR USB dongle and [NGSoftFM](https://github.com/f4exb/ngsoftfm), streams it to an Icecast server, and exposes an HTTP API for tuning. An LMS plugin integrates it into the Radio menu with a configurable station list.

![FM Radio plugin icon](LMSPlugin/FMRadio/HTML/EN/plugins/FMRadio/html/images/FMRadio_svg.png)

---

## Architecture

```
RTL-SDR dongle
      ↓
   NGSoftFM  (FM demodulation, stereo PCM)
      ↓
  named pipe
      ↓
   ffmpeg  (encode to MP3)
      ↓
   Icecast  (HTTP audio stream)
      ↑
 fm-daemon  (HTTP API — tuning control)
      ↑
 LMS Plugin  (Radio menu, station list, settings)
```

---

## Prerequisites

- Linux server (Debian/Ubuntu recommended)
- RTL-SDR USB dongle connected and working
- [NGSoftFM](https://github.com/f4exb/ngsoftfm) built and installed (see note below)
- `ffmpeg` installed (`apt install ffmpeg`)
- Icecast2 server running (`apt install icecast2`)
- Lyrion Music Server 8.x or 9.x

### RTL-SDR USB dongle

RTL-SDR is a type of software-defined radio (SDR) that uses a cheap DVB-T TV tuner dongle as a wideband radio receiver. Originally designed for receiving digital TV, these dongles can be repurposed to receive a wide range of radio signals — including FM radio — when used with the right software. A basic dongle from China costing around 10 EUR works perfectly fine for FM reception.

> **Note:** Getting your RTL-SDR dongle working and building NGSoftFM is outside the scope of this guide. See the [rtl-sdr quickstart](https://www.rtl-sdr.com/rtl-sdr-quick-start-guide/) and the [NGSoftFM README](https://github.com/f4exb/ngsoftfm) for instructions. Verify your setup works by running `softfm -t rtlsdr -c freq=90800000 -R -` before proceeding.

---

## Daemon Setup

The daemon (`fm-daemon.py`) controls NGSoftFM and ffmpeg, and exposes an HTTP API for tuning.

### 1. Configure

Edit `daemon/fm-daemon.py` and fill in the configuration section at the top:

```python
SOFTFM_BIN         = "/usr/local/bin/softfm"       # path to your softfm binary
ICECAST_HOST       = "your-icecast-host"            # Icecast hostname or IP
ICECAST_PORT       = 8000                           # Icecast port
ICECAST_MOUNT      = "/fm"                          # Icecast mount point
ICECAST_SOURCE     = "your-source-password"         # Icecast source password
ICECAST_ADMIN_USER = "admin"                        # Icecast admin username
ICECAST_ADMIN_PASS = "your-admin-password"          # Icecast admin password
DAEMON_PORT        = 8080                           # port for this daemon's HTTP API
STARTUP_FREQ       = 90800000                       # startup frequency in Hz
```

### 2. Install

```bash
sudo cp daemon/fm-daemon.py /usr/local/bin/fm-daemon.py
sudo chmod +x /usr/local/bin/fm-daemon.py
```

### 3. Install as a systemd service

```bash
sudo cp daemon/fm-daemon.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable fm-daemon
sudo systemctl start fm-daemon
```

Check that it is running:

```bash
sudo systemctl status fm-daemon
```

### 4. Test the API

```bash
# Check status
curl http://localhost:8080/status

# Tune to 93.9 MHz and redirect to stream
curl -L http://localhost:8080/listen/93.9

# Tune via POST
curl -X POST "http://localhost:8080/tune?freq=93900000"

# Stop
curl -X POST http://localhost:8080/stop
```

### API reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/status` | Returns current status and frequency as JSON |
| GET | `/listen/90.8` | Tune to 90.8 MHz, redirect to Icecast stream |
| GET | `/listen/90800000` | Same, using Hz |
| POST | `/tune?freq=90800000` | Tune without redirect |
| POST | `/stop` | Stop reception |

---

## LMS Plugin Installation

### Manual install

1. Copy the `LMSPlugin/FMRadio` folder into your LMS plugin directory:
   - Docker: `/config/cache/Plugins/FMRadio`
   - Standard: `/usr/share/squeezeboxserver/Plugins/FMRadio`

2. Add your station icon (optional):
   Place a PNG file at `LMSPlugin/FMRadio/HTML/EN/plugins/FMRadio/html/images/FMRadio_svg.png`

3. Restart LMS.

### Via external repository

Add the following URL in LMS under **Settings → Plugins → Add repository**:

```
https://raw.githubusercontent.com/macsatcom/Lyrion_FM_Radio/main/repo.xml
```

After adding the repository, FM Radio will appear in the plugin list and can be installed from there.

### Plugin configuration

After installation, go to **Settings → Plugins → FM Radio → Settings** and configure:

- **Daemon URL** — URL to your fm-daemon, e.g. `http://192.168.1.10:8080`
- **Icecast Stream URL** — URL to your Icecast stream, e.g. `http://192.168.1.10:8000/fm`
- **Stations** — list of stations in `name|MHz` format, one per line:

```
DR P1|90.8
DR P3|93.9
DR P4 København|96.5
Radio 100|100.0
```

The plugin will appear under **Radio → FM Radio** in LMS.

---

## License

GNU GPL
