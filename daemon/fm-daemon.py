#!/usr/bin/env python3
"""
FM Radio Daemon
Controls softfm + ffmpeg pipeline and streams to Icecast.
Provides an HTTP API for tuning and stream control.

See README.md for setup instructions.

Configuration: edit the constants below, or override any of them with environment
variables (useful for Docker). The --device / -d flag selects which RTL-SDR dongle
to use when multiple are connected.
"""

import os
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

SOFTFM_BIN         = os.environ.get("SOFTFM_BIN",         "/usr/local/bin/softfm")
FIFO_PATH          = os.environ.get("FIFO_PATH",           "/run/fm_pipe")

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

# ─── State ────────────────────────────────────────────────────────────────────

state = {
    "status": "stopped",
    "freq":   None,
}

softfm_proc = None
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

def update_icecast_metadata(station_name, freq):
    freq_mhz = freq / 1_000_000
    title = f"{station_name} ({freq_mhz:.1f} MHz)" if station_name else f"{freq_mhz:.1f} MHz"
    try:
        params = urlencode({"mode": "updinfo", "mount": ICECAST_MOUNT, "song": title})
        url = f"http://{ICECAST_HOST}:{ICECAST_PORT}/admin/metadata?{params}"
        req = urllib.request.Request(url)
        creds = base64.b64encode(f"{ICECAST_ADMIN_USER}:{ICECAST_ADMIN_PASS}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")
        urllib.request.urlopen(req, timeout=3)
        print(f"[daemon] Icecast metadata updated: {title}")
    except Exception as e:
        print(f"[daemon] Metadata update failed: {e}")

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

    ffmpeg_proc = subprocess.Popen([
        "ffmpeg", "-loglevel", "error",
        "-f", "s16le", "-ar", "48000", "-ac", "2",
        "-i", FIFO_PATH,
        "-c:a", "libmp3lame", "-b:a", "192k",
        "-f", "mp3",
        ice_url,
    ])
    time.sleep(0.5)
    threading.Thread(target=keep_fifo_open, daemon=True).start()
    print(f"[daemon] ffmpeg started")

def stop_softfm():
    global softfm_proc
    if softfm_proc and softfm_proc.poll() is None:
        softfm_proc.terminate()
        try:
            softfm_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            softfm_proc.kill()
        softfm_proc = None
        print("[daemon] softfm stopped")

def start_softfm(freq):
    global softfm_proc
    stop_softfm()
    time.sleep(0.3)
    softfm_proc = subprocess.Popen([
        SOFTFM_BIN, "-t", "rtlsdr", "-d", str(RTL_DEVICE), "-c", f"freq={freq}", "-R", "-",
    ], stdout=open(FIFO_PATH, "wb"), stderr=subprocess.DEVNULL)
    print(f"[daemon] softfm tuned to {freq / 1_000_000:.1f} MHz (device {RTL_DEVICE})")

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
    """Tunes to a new frequency. Only restarts softfm — ffmpeg keeps running."""
    def _do_tune():
        with state_lock:
            start_softfm(freq)
            state["status"] = "playing"
            state["freq"]   = freq
        time.sleep(3)
        update_icecast_metadata(None, freq)
    threading.Thread(target=_do_tune, daemon=True).start()

def stop():
    with state_lock:
        stop_softfm()
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
