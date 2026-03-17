# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This project streams FM radio (via RTL-SDR dongle) to a Lyrion Music Server (LMS). It has two components:

1. **`daemon/fm-daemon.py`** — Python HTTP daemon that controls a `rtl_fm → named pipe → ffmpeg → Icecast` pipeline, decodes RDS metadata via `redsea`, and exposes a tuning API on port 8080.
2. **`LMSPlugin/FMRadio/`** — Perl LMS plugin (OPMLBased) that adds FM Radio to the LMS Radio menu with a configurable station list.

## Architecture

```
RTL-SDR → rtl_fm (171 kHz) ──┬─→ fm-stereo.py (scipy) → /run/fm_pipe → ffmpeg stereo 192k → Icecast
                               │    (bandpass pilot 19kHz → ×2 → carrier 38kHz              ↑
                               │     bandpass L-R 23-53kHz × carrier → lowpass 15kHz        │
                               │     de-emphasis 50µs → matrix L/R → resample 48kHz)        │
                               │                                                              │
                               └─→ redsea (RDS JSON) → rds_reader thread ────────────────────┘
                                                               ↑
                                         fm-daemon HTTP API ───┘
                                                 ↑
                                         LMS Plugin (Perl)
```

- `rtl_fm` outputs the FM multiplex at 171 kHz — high enough to preserve the RDS subcarrier at 57 kHz.
- `tee_to_stereo_and_redsea` splits the `rtl_fm` output to `fm-stereo.py` (audio) and `redsea` (RDS) simultaneously.
- `fm-stereo.py` uses scipy to decode the FM stereo multiplex: extracts the 19 kHz pilot, squares it to get a phase-coherent 38 kHz carrier, demodulates the L-R DSB-SC subcarrier (23–53 kHz), applies de-emphasis, matrices to L/R, and resamples to 48 kHz stereo s16le.
- `ffmpeg` encodes the 48 kHz stereo stream to MP3 at 192k (no filtering needed — stereo decoder already lowpassed at 15 kHz).
- `redsea` emits newline-delimited JSON; `rds_reader` parses `"ps"` (station name) and `"radiotext"` (current programme) and pushes changes to Icecast via `/admin/metadata`.
- On retune, RDS state is cleared and Icecast metadata is set to the frequency string until RDS arrives.
- Set `STEREO=0` to skip `fm-stereo.py` and fall back to mono 128k MP3 (no scipy dependency).

## Key Files

- `daemon/fm-daemon.py` — All configuration (ports, startup frequency, RTL_FM_RATE) is at the top. Set `RDS_DEBUG=1` to print every raw redsea JSON line. Set `STEREO=0` to disable stereo decoding.
- `daemon/fm-stereo.py` — Standalone FM stereo decoder (scipy DSP). Reads FM multiplex (s16le, 171 kHz mono) from stdin; writes decoded stereo (s16le, 48 kHz) to stdout. Tune `STEREO_GAIN` (default 2.0) and `DE_EMPH_TC` (default 50e-6 for EU) via env vars.
- `daemon/fm-daemon.service` — systemd unit; runs as `root`, restarts on failure.
- `docker/Dockerfile` — Builds `redsea` from source (windytan/redsea); uses `rtl_fm` from the `rtl-sdr` apt package; includes `python3-scipy` for stereo decoding.
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
- `RTL_FM_BIN`, `REDSEA_BIN`, `STEREO_SCRIPT` — binary paths (all in Docker image)
- `RTL_FM_RATE` — sample rate for rtl_fm (default 171000 Hz; must be ≥ 114 kHz for RDS)
- `STEREO` — set to `0` to disable stereo decoding (fallback to mono 128k)
- `ICECAST_HOST`, `ICECAST_PORT`, `ICECAST_MOUNT`, `ICECAST_SOURCE`, `ICECAST_ADMIN_*`
- `DAEMON_PORT`, `STARTUP_FREQ`, `RTL_DEVICE`

Stereo decoder env vars (in `daemon/fm-stereo.py`):
- `STEREO_GAIN` — L-R signal gain relative to L+R (default 2.0; theoretical value)
- `DE_EMPH_TC` — de-emphasis time constant in seconds (default `50e-6` = EU; use `75e-6` for Americas)

LMS plugin settings (daemon URL, Icecast URL, station list) are configured via **LMS Settings → Plugins → FM Radio**.

## Audio quality note

The pipeline produces stereo MP3 at 192k. `fm-stereo.py` bandpass-filters the FM multiplex to extract the L-R subcarrier (23–53 kHz), demodulates with a phase-coherent 38 kHz carrier derived from the pilot tone, then matrices to L and R channels with de-emphasis applied. Set `STEREO=0` for mono 128k if scipy is unavailable.
