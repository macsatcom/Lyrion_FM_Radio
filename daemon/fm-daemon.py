#!/usr/bin/env python3
"""
FM Radio Daemon
Controls rtl_fm + ffmpeg pipeline and streams to Icecast.
Uses redsea to decode RDS (PS / RadioText) from the FM multiplex and push
live metadata updates to Icecast — the same pattern as the DAB daemon.
Provides an HTTP API for tuning and stream control.

See README.md for setup instructions.

Configuration: edit the constants below, or override any of them with environment
variables (useful for Docker). The --device / -d flag selects which RTL-SDR dongle
to use when multiple are connected.
"""

import os
import re
import stat
import base64
import signal
import subprocess
import threading
import time
import json
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode
import urllib.parse
import urllib.request

# ─── Configuration ────────────────────────────────────────────────────────────
# Edit these values to match your setup, or override via environment variables.

RTL_FM_BIN         = os.environ.get("RTL_FM_BIN",         "/usr/bin/rtl_fm")
REDSEA_BIN         = os.environ.get("REDSEA_BIN",         "/usr/local/bin/redsea")
FIFO_PATH          = os.environ.get("FIFO_PATH",           "/run/fm_pipe")

# Sample rate for rtl_fm output. Must be >= 114 kHz to capture the RDS
# subcarrier at 57 kHz (Nyquist). 171 kHz is the rate redsea recommends.
RTL_FM_RATE        = int(os.environ.get("RTL_FM_RATE",     "171000"))

ICECAST_HOST       = os.environ.get("ICECAST_HOST",        "your-icecast-host")
ICECAST_PORT       = int(os.environ.get("ICECAST_PORT",    "8000"))
ICECAST_MOUNT      = os.environ.get("ICECAST_MOUNT",       "/fm")
ICECAST_SOURCE     = os.environ.get("ICECAST_SOURCE",      "your-source-password")
ICECAST_ADMIN_USER = os.environ.get("ICECAST_ADMIN_USER",  "admin")
ICECAST_ADMIN_PASS = os.environ.get("ICECAST_ADMIN_PASS",  "your-admin-password")

DAEMON_PORT        = int(os.environ.get("DAEMON_PORT",     "8080"))

# Default startup frequency in Hz (e.g. 90800000 = 90.8 MHz)
STARTUP_FREQ       = int(os.environ.get("STARTUP_FREQ",    "90800000"))

# RTL-SDR device index (0 = first dongle). Override with --device / -d or RTL_DEVICE env var.
RTL_DEVICE         = int(os.environ.get("RTL_DEVICE",      "0"))

# Set RDS_DEBUG=1 to print every raw redsea JSON line for inspection.
RDS_DEBUG          = os.environ.get("RDS_DEBUG", "0") == "1"

# ─── State ────────────────────────────────────────────────────────────────────

state = {
    "status": "stopped",
    "freq":   None,
    "rds_ps": None,   # Programme Service name (station name, up to 8 chars)
    "rds_rt": None,   # RadioText (current programme/song text)
}

rtl_fm_proc = None
redsea_proc = None
ffmpeg_proc = None
state_lock  = threading.Lock()

# ─── FIFO ─────────────────────────────────────────────────────────────────────

def ensure_fifo():
    if os.path.exists(FIFO_PATH):
        if not stat.S_ISFIFO(os.stat(FIFO_PATH).st_mode):
            os.remove(FIFO_PATH)
            os.mkfifo(FIFO_PATH)
    else:
        os.mkfifo(FIFO_PATH)

def keep_fifo_open():
    """Keeps the write end of the FIFO open so ffmpeg never gets EOF between station changes."""
    while True:
        try:
            fd = os.open(FIFO_PATH, os.O_WRONLY)
            while True:
                time.sleep(60)
        except Exception:
            time.sleep(1)

# ─── Icecast metadata ─────────────────────────────────────────────────────────

def update_icecast_metadata(title):
    """Push Current Song title to Icecast. Tries source password first, then admin.

    Icecast 2.4 expects the song parameter URL-encoded as Latin-1, not UTF-8.
    """
    song = urllib.parse.quote(title, encoding="latin-1", errors="replace")
    params = f"mode=updinfo&mount={urllib.parse.quote(ICECAST_MOUNT)}&song={song}"
    url = f"http://{ICECAST_HOST}:{ICECAST_PORT}/admin/metadata?{params}"
    for user, pw in [("source", ICECAST_SOURCE), (ICECAST_ADMIN_USER, ICECAST_ADMIN_PASS)]:
        try:
            req = urllib.request.Request(url)
            creds = base64.b64encode(f"{user}:{pw}".encode()).decode()
            req.add_header("Authorization", f"Basic {creds}")
            urllib.request.urlopen(req, timeout=3)
            print(f"[daemon] Metadata updated: {title}")
            return
        except urllib.error.HTTPError as e:
            if e.code != 401:
                print(f"[daemon] Metadata update failed: {e}")
                return
        except Exception as e:
            print(f"[daemon] Metadata update failed: {e}")
            return
    print("[daemon] Metadata update failed: authentication failed")

# ─── Pipeline ─────────────────────────────────────────────────────────────────

def start_ffmpeg(freq=None):
    global ffmpeg_proc
    ensure_fifo()

    freq_mhz = f"{freq / 1_000_000:.1f} MHz" if freq else "FM Radio"
    ice_url = (
        f"icecast://source:{ICECAST_SOURCE}@{ICECAST_HOST}:{ICECAST_PORT}{ICECAST_MOUNT}"
        f"?ice-name={urllib.parse.quote(freq_mhz)}"
        f"&ice-description={urllib.parse.quote('FM Radio via RTL-SDR')}"
        f"&ice-genre=FM"
    )

    # rtl_fm outputs the FM multiplex at RTL_FM_RATE Hz (mono, s16le).
    # The lowpass filter strips the pilot (19 kHz), stereo (38 kHz), and
    # RDS (57 kHz) subcarriers, leaving clean mono audio for listeners.
    ffmpeg_proc = subprocess.Popen([
        "ffmpeg", "-loglevel", "error",
        "-f", "s16le", "-ar", str(RTL_FM_RATE), "-ac", "1",
        "-i", FIFO_PATH,
        "-af", f"lowpass=f=15000",
        "-ar", "48000", "-ac", "1",
        "-c:a", "libmp3lame", "-b:a", "128k",
        "-f", "mp3",
        ice_url,
    ])
    time.sleep(0.5)
    threading.Thread(target=keep_fifo_open, daemon=True).start()
    print("[daemon] ffmpeg started")

def stop_rtl_fm():
    global rtl_fm_proc, redsea_proc
    for proc in (rtl_fm_proc, redsea_proc):
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    rtl_fm_proc = None
    redsea_proc = None

def tee_to_fifo_and_redsea(rtl_stdout, redsea_stdin):
    """
    Reads rtl_fm output and writes it to both the audio FIFO (for ffmpeg)
    and to redsea's stdin (for RDS decoding), acting as an in-process tee.
    """
    try:
        fifo = open(FIFO_PATH, "wb")
    except Exception as e:
        print(f"[daemon] tee: failed to open FIFO: {e}")
        return
    try:
        while True:
            data = rtl_stdout.read(4096)
            if not data:
                break
            try:
                fifo.write(data)
            except Exception:
                pass
            try:
                redsea_stdin.write(data)
            except Exception:
                break
    finally:
        fifo.close()
        try:
            redsea_stdin.close()
        except Exception:
            pass

def rds_reader(redsea_stdout):
    """
    Reads redsea's JSON output line by line and updates Icecast when PS or RT changes.
    redsea emits one JSON object per RDS group, e.g.:
      {"pi":"0x6204","ps":"DR P 1  ","pty":1,"pty_name":"News/Info"}
      {"rt":"Nu: K-Live med Popsmart: Iransk kulturarv ødelagt"}
    """
    for raw_line in redsea_stdout:
        if RDS_DEBUG:
            print(f"[rds raw] {raw_line.decode('utf-8', errors='replace').strip()!r}")
        try:
            data = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            continue

        ps = data.get("ps", "").strip() if "ps" in data else None
        # redsea uses "radiotext" as the key for RDS RadioText (RT)
        rt = data.get("radiotext", "").strip() if "radiotext" in data else None

        if ps:
            with state_lock:
                old_ps = state["rds_ps"]
                state["rds_ps"] = ps
                current_rt = state["rds_rt"]
            if RDS_DEBUG:
                print(f"[rds] PS: {ps!r}")
            # If PS just arrived and there's no RT yet, update Icecast with station name
            if ps != old_ps and not current_rt:
                update_icecast_metadata(ps.strip())

        if rt:
            with state_lock:
                old_rt = state["rds_rt"]
                state["rds_rt"] = rt
                current_ps = state["rds_ps"]
            if rt != old_rt:
                title = f"{current_ps.strip()}: {rt}" if current_ps else rt
                update_icecast_metadata(title)
                if RDS_DEBUG:
                    print(f"[rds] RT updated: {title!r}")

def start_rtl_fm(freq):
    global rtl_fm_proc, redsea_proc
    stop_rtl_fm()
    time.sleep(0.3)

    # rtl_fm with -s and -r both set to RTL_FM_RATE outputs the FM multiplex
    # at that sample rate — high enough to include the 57 kHz RDS subcarrier.
    rtl_fm_proc = subprocess.Popen([
        RTL_FM_BIN,
        "-f", str(freq),
        "-M", "fm",
        "-d", str(RTL_DEVICE),
        "-s", str(RTL_FM_RATE),
        "-r", str(RTL_FM_RATE),
        "-",
    ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    redsea_proc = subprocess.Popen([
        REDSEA_BIN, "-r", str(RTL_FM_RATE),
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    threading.Thread(
        target=tee_to_fifo_and_redsea,
        args=(rtl_fm_proc.stdout, redsea_proc.stdin),
        daemon=True,
    ).start()
    threading.Thread(
        target=rds_reader,
        args=(redsea_proc.stdout,),
        daemon=True,
    ).start()

    print(f"[daemon] rtl_fm tuned to {freq / 1_000_000:.1f} MHz (device {RTL_DEVICE}, rate {RTL_FM_RATE} Hz)")

def stop_ffmpeg():
    global ffmpeg_proc
    if ffmpeg_proc and ffmpeg_proc.poll() is None:
        ffmpeg_proc.terminate()
        try:
            ffmpeg_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            ffmpeg_proc.kill()
        ffmpeg_proc = None

def tune(freq):
    """Tunes to a new frequency. Only restarts rtl_fm — ffmpeg keeps running."""
    def _do_tune():
        with state_lock:
            state["rds_ps"] = None
            state["rds_rt"] = None
            start_rtl_fm(freq)
            state["status"] = "playing"
            state["freq"]   = freq
        freq_mhz = freq / 1_000_000
        update_icecast_metadata(f"{freq_mhz:.1f} MHz")
    threading.Thread(target=_do_tune, daemon=True).start()

def stop():
    with state_lock:
        stop_rtl_fm()
        state["status"] = "stopped"
        state["freq"]   = None

# ─── HTTP API ─────────────────────────────────────────────────────────────────

def json_response(handler, code, data):
    body = json.dumps(data, indent=2).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", len(body))
    handler.end_headers()
    handler.wfile.write(body)

class FMHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"[http] {self.address_string()} {fmt % args}")

    def do_GET(self):
        parsed = urlparse(self.path)

        # GET /status
        if parsed.path == "/status":
            with state_lock:
                json_response(self, 200, state)

        # GET /listen/90.8 or /listen/90800000
        elif parsed.path.startswith("/listen/"):
            raw = parsed.path[len("/listen/"):]
            freq = None
            try:
                val = float(raw)
                # Values below 2200 are treated as MHz, otherwise Hz
                freq = int(val * 1_000_000) if val < 2200 else int(val)
            except ValueError:
                pass

            if freq and 10_000_000 <= freq <= 2_200_000_000:
                tune(freq)
                icecast_http = f"http://{ICECAST_HOST}:{ICECAST_PORT}{ICECAST_MOUNT}"
                self.send_response(302)
                self.send_header("Location", icecast_http)
                self.end_headers()
            else:
                json_response(self, 400, {"error": f"invalid frequency: {raw}"})

        else:
            json_response(self, 404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        # POST /tune?freq=90800000
        if parsed.path == "/tune":
            freq_str = qs.get("freq", [None])[0]
            if not freq_str or not freq_str.isdigit():
                json_response(self, 400, {"error": "missing or invalid freq"})
                return
            freq = int(freq_str)
            if not (10_000_000 <= freq <= 2_200_000_000):
                json_response(self, 400, {"error": "freq out of range (10M-2.2G)"})
                return
            tune(freq)
            json_response(self, 200, {"ok": True, "freq": freq})

        # POST /stop
        elif parsed.path == "/stop":
            stop()
            json_response(self, 200, {"ok": True, "status": "stopped"})

        else:
            json_response(self, 404, {"error": "not found"})

# ─── Entrypoint ───────────────────────────────────────────────────────────────

def shutdown_handler(sig, frame):
    print("\n[daemon] shutting down...")
    stop()
    if ffmpeg_proc and ffmpeg_proc.poll() is None:
        ffmpeg_proc.terminate()
    os._exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FM Radio Daemon")
    parser.add_argument(
        "-d", "--device",
        type=int,
        default=RTL_DEVICE,
        metavar="INDEX",
        help="RTL-SDR device index to use (default: %(default)s). "
             "Run 'rtl_test' to list connected devices.",
    )
    args = parser.parse_args()
    RTL_DEVICE = args.device

    signal.signal(signal.SIGINT,  shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    print(f"[daemon] using RTL-SDR device index {RTL_DEVICE}")
    print("[daemon] starting ffmpeg pipeline...")
    start_ffmpeg(freq=STARTUP_FREQ)

    print(f"[daemon] HTTP API listening on port {DAEMON_PORT}")
    print("[daemon] Endpoints:")
    print("  GET  /status")
    print("  GET  /listen/90.8      (MHz)")
    print("  GET  /listen/90800000  (Hz)")
    print("  POST /tune?freq=90800000")
    print("  POST /stop")

    tune(STARTUP_FREQ)
    print(f"[daemon] auto-started on {STARTUP_FREQ / 1_000_000:.1f} MHz")

    server = HTTPServer(("0.0.0.0", DAEMON_PORT), FMHandler)
    server.serve_forever()
