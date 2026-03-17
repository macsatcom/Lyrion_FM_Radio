# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This project streams FM radio (via RTL-SDR dongle) to a Lyrion Music Server (LMS). It has two components:

1. **`daemon/fm-daemon.py`** — Python HTTP daemon that controls a `rtl_fm → named pipe → ffmpeg → Icecast` pipeline, decodes RDS metadata via `redsea`, and exposes a tuning API on port 8080.
2. **`LMSPlugin/FMRadio/`** — Perl LMS plugin (OPMLBased) that adds FM Radio to the LMS Radio menu with a configurable station list.

## Architecture

```
RTL-SDR → rtl_fm (171 kHz) ─── tee (Python) ──→ /run/fm_pipe (FIFO) → ffmpeg → Icecast
                                                                                      ↑
                                        └──→ redsea (RDS JSON) → rds_reader thread ──┘
                                                                         ↑
                                              fm-daemon HTTP API ────────┘
                                                      ↑
                                              LMS Plugin (Perl)
```

- `rtl_fm` outputs the FM multiplex at 171 kHz — high enough to preserve the RDS subcarrier at 57 kHz.
- A Python tee thread (`tee_to_fifo_and_redsea`) splits the `rtl_fm` output to both the audio FIFO and `redsea`'s stdin simultaneously.
- `ffmpeg` applies a 15 kHz low-pass filter to strip the pilot, stereo, and RDS subcarriers before encoding to MP3 (mono 128k).
- `redsea` emits newline-delimited JSON; `rds_reader` parses `"ps"` (station name) and `"radiotext"` (current programme) and pushes changes to Icecast via `/admin/metadata`.
- On retune, RDS state is cleared and Icecast metadata is set to the frequency string until RDS arrives.

## Key Files

- `daemon/fm-daemon.py` — All configuration (ports, startup frequency, RTL_FM_RATE) is at the top. Set `RDS_DEBUG=1` to print every raw redsea JSON line.
- `daemon/fm-daemon.service` — systemd unit; runs as `root`, restarts on failure.
- `docker/Dockerfile` — Builds `redsea` from source (windytan/redsea); uses `rtl_fm` from the `rtl-sdr` apt package.
- `LMSPlugin/FMRadio/Plugin.pm` — Main plugin class; registers feed handler and reads prefs.
- `LMSPlugin/FMRadio/Settings.pm` — LMS settings page handler (daemon_url, icecast_url, stations).
- `LMSPlugin/FMRadio/install.xml` — Plugin manifest (version, target LMS ≥ 7.6).

## Daemon API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/status` | JSON status, current frequency, and RDS state (rds_ps, rds_rt) |
| GET | `/listen/90.8` | Tune (MHz) + redirect to Icecast stream |
| GET | `/listen/90800000` | Tune (Hz) + redirect |
| POST | `/tune?freq=90800000` | Tune without redirect |
| POST | `/stop` | Stop rtl_fm and redsea |

## Deployment Commands

```bash
# Run the daemon directly (for testing — needs rtl_fm and redsea in PATH)
python3 daemon/fm-daemon.py

# Enable RDS debug logging
RDS_DEBUG=1 python3 daemon/fm-daemon.py

# Install daemon as systemd service
sudo cp daemon/fm-daemon.py /usr/local/bin/fm-daemon.py
sudo chmod +x /usr/local/bin/fm-daemon.py
sudo cp daemon/fm-daemon.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now fm-daemon
sudo journalctl -u fm-daemon -f

# Docker
cd docker && cp .env.example .env && docker compose up --build

# Test API
curl http://localhost:8080/status
curl -X POST "http://localhost:8080/tune?freq=93900000"
```

## Configuration

Key constants at the top of `daemon/fm-daemon.py`:
- `RTL_FM_BIN`, `REDSEA_BIN` — binary paths (both in Docker image)
- `RTL_FM_RATE` — sample rate for rtl_fm (default 171000 Hz; must be ≥ 114 kHz for RDS)
- `ICECAST_HOST`, `ICECAST_PORT`, `ICECAST_MOUNT`, `ICECAST_SOURCE`, `ICECAST_ADMIN_*`
- `DAEMON_PORT`, `STARTUP_FREQ`, `RTL_DEVICE`

LMS plugin settings (daemon URL, Icecast URL, station list) are configured via **LMS Settings → Plugins → FM Radio**.

## Audio quality note

The pipeline produces mono audio (rtl_fm's FM demodulation is mono). The 15 kHz low-pass filter removes the stereo pilot (19 kHz), L−R subcarrier (38 kHz), and RDS subcarrier (57 kHz). Bitrate: 128k MP3.
