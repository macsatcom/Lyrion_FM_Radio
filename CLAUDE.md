# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This project streams FM radio (via RTL-SDR dongle + SoftFM) to a Lyrion Music Server (LMS). It has two components:

1. **`daemon/fm-daemon.py`** — Python HTTP daemon that controls a `softfm → named pipe → ffmpeg → Icecast` pipeline and exposes a tuning API on port 8080.
2. **`LMSPlugin/FMRadio/`** — Perl LMS plugin (OPMLBased) that adds FM Radio to the LMS Radio menu with a configurable station list.

## Architecture

```
RTL-SDR → SoftFM → /run/fm_pipe (FIFO) → ffmpeg → Icecast
                                                      ↑
                              fm-daemon HTTP API ─────┘
                                      ↑
                              LMS Plugin (Perl)
```

- **Tuning** restarts only `softfm`; `ffmpeg` and Icecast stay running continuously to avoid stream interruptions.
- The FIFO write-end is kept open by a background thread so ffmpeg never gets EOF between station changes.
- Station list is stored in LMS prefs as `name|MHz` lines and rendered as OPML feed items pointing to `GET /listen/<MHz>`.

## Key Files

- `daemon/fm-daemon.py` — All configuration (Icecast credentials, ports, startup frequency) is at the top of this file in clearly-marked constants.
- `daemon/fm-daemon.service` — systemd unit; runs as `root`, restarts on failure.
- `LMSPlugin/FMRadio/Plugin.pm` — Main plugin class; registers feed handler and reads prefs.
- `LMSPlugin/FMRadio/Settings.pm` — LMS settings page handler (daemon_url, icecast_url, stations).
- `LMSPlugin/FMRadio/install.xml` — Plugin manifest (version, target LMS ≥ 7.6).

## Daemon API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/status` | JSON status and current frequency |
| GET | `/listen/90.8` | Tune (MHz) + redirect to Icecast stream |
| GET | `/listen/90800000` | Tune (Hz) + redirect |
| POST | `/tune?freq=90800000` | Tune without redirect |
| POST | `/stop` | Stop softfm |

## Deployment Commands

```bash
# Run the daemon directly (for testing)
python3 daemon/fm-daemon.py

# Install daemon as systemd service
sudo cp daemon/fm-daemon.py /usr/local/bin/fm-daemon.py
sudo chmod +x /usr/local/bin/fm-daemon.py
sudo cp daemon/fm-daemon.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now fm-daemon

# Check daemon logs
sudo journalctl -u fm-daemon -f

# Test API
curl http://localhost:8080/status
curl -X POST "http://localhost:8080/tune?freq=93900000"

# Install LMS plugin (Docker LMS)
cp -r LMSPlugin/FMRadio /config/cache/Plugins/
# Then restart LMS
```

## Configuration

Edit the constants at the top of `daemon/fm-daemon.py` before deploying:
- `SOFTFM_BIN`, `ICECAST_HOST`, `ICECAST_PORT`, `ICECAST_MOUNT`, `ICECAST_SOURCE`
- `ICECAST_ADMIN_USER`, `ICECAST_ADMIN_PASS`, `DAEMON_PORT`, `STARTUP_FREQ`

LMS plugin settings (daemon URL, Icecast URL, station list) are configured via **LMS Settings → Plugins → FM Radio**.
