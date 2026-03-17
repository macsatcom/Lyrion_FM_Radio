#!/usr/bin/env python3
"""
FM stereo decoder.

Reads FM multiplex (s16le, 171 kHz, mono) from stdin.
Writes decoded stereo PCM (s16le, 48 kHz, 2-channel interleaved) to stdout.

Signal model of the FM stereo multiplex (after FM demodulation by rtl_fm):
  s(t) = (L+R)/2                         ←  mono programme    (0–15 kHz)
         + pilot · cos(2π·19k·t)          ←  stereo pilot tone (9% of dev)
         + (L-R)/2 · cos(2π·38k·t)        ←  L-R DSB-SC        (23–53 kHz)
         + RDS @ 57 kHz                   ←  handled by redsea, not here

Processing pipeline:
  1. BPF input at 19 kHz  → square  → BPF at 38 kHz  = phase-locked carrier
  2. LPF input at 15 kHz                              = L+R sum signal
  3. BPF input at 23–53 kHz  × carrier  → LPF 15 kHz = L-R diff signal
  4. De-emphasis (50 µs / EU default, 75 µs / Americas)
  5. Matrix:  L = sum + STEREO_GAIN · diff
              R = sum − STEREO_GAIN · diff
  6. Resample 171 kHz → 48 kHz  (UP=16, DOWN=57), clip, interleave, s16le out

STEREO_GAIN derivation:
  After synchronous demodulation with a unit-amplitude carrier,
  the L-R signal is halved relative to L+R (because cos²(ωt) = (1+cos(2ωt))/2).
  Both L+R and L-R occupy 45% of full FM deviation, so after demodulation:
    lpr = 0.45 · (L+R)
    lmr = 0.45 · (L-R)/2  = 0.225 · (L-R)
  STEREO_GAIN = 0.45/0.225 = 2.0 yields  L = 0.9·L, R = 0.9·R  (correct stereo).
"""
import os
import sys

try:
    import numpy as np
    from scipy import signal as sig
except ImportError:
    print("[fm-stereo] scipy not found — install python3-scipy", file=sys.stderr)
    sys.exit(1)

# ─── Configuration ────────────────────────────────────────────────────────────

RATE        = int(os.environ.get("RTL_FM_RATE",  "171000"))
OUT_RATE    = 48_000
CHUNK       = 8_192                                           # input samples per block
STEREO_GAIN = float(os.environ.get("STEREO_GAIN", "2.0"))
# De-emphasis: 50e-6 = Europe/Australia, 75e-6 = Americas/Korea/Japan
DE_EMPH_TC  = float(os.environ.get("DE_EMPH_TC",  "50e-6"))

# Resample ratio: gcd(171000, 48000) = 3000  →  UP=16, DOWN=57
UP, DOWN = 16, 57

# ─── Filter design (done once at startup) ────────────────────────────────────

nyq = RATE / 2.0

# L+R: lowpass 15 kHz (strips pilot, L-R subcarrier, RDS)
sos_sum   = sig.butter(5, 15_000 / nyq,                  'low',      output='sos')

# Pilot: narrow bandpass around 19 kHz pilot tone
sos_pilot = sig.butter(5, [18_500 / nyq, 19_500 / nyq],  'bandpass', output='sos')

# Carrier: bandpass at 38 kHz (cleans up squared pilot)
sos_carr  = sig.butter(5, [37_000 / nyq, 39_000 / nyq],  'bandpass', output='sos')

# L-R DSB-SC: bandpass covering the stereo subcarrier sidebands
sos_diff  = sig.butter(5, [22_000 / nyq, 54_000 / nyq],  'bandpass', output='sos')

# Post-demodulation lowpass for L-R
sos_dlpf  = sig.butter(5, 15_000 / nyq,                  'low',      output='sos')

# De-emphasis: 1st-order RC   H(z) = α / (1 − (1−α)z⁻¹)
_dt    = 1.0 / RATE
_alpha = _dt / (DE_EMPH_TC + _dt)
de_b   = np.array([_alpha],               dtype=np.float64)
de_a   = np.array([1.0, -(1.0 - _alpha)], dtype=np.float64)

# ─── Filter states (maintained across chunks for seamless audio) ──────────────

zi_sum   = sig.sosfilt_zi(sos_sum)
zi_pilot = sig.sosfilt_zi(sos_pilot)
zi_carr  = sig.sosfilt_zi(sos_carr)
zi_diff  = sig.sosfilt_zi(sos_diff)
zi_dlpf  = sig.sosfilt_zi(sos_dlpf)
zi_de_s  = sig.lfilter_zi(de_b, de_a)   # de-emphasis state for L+R
zi_de_d  = sig.lfilter_zi(de_b, de_a)   # de-emphasis state for L-R


def process(pcm_int16: np.ndarray) -> np.ndarray:
    global zi_sum, zi_pilot, zi_carr, zi_diff, zi_dlpf, zi_de_s, zi_de_d

    x = pcm_int16.astype(np.float32) / 32768.0   # normalise to ±1.0

    # 1. Extract L+R sum signal
    lpr, zi_sum = sig.sosfilt(sos_sum, x, zi=zi_sum)

    # 2. Extract pilot → square → clean 38 kHz phase-coherent carrier
    pilot, zi_pilot = sig.sosfilt(sos_pilot, x, zi=zi_pilot)
    squared         = pilot ** 2                 # → DC + 38 kHz component
    carrier, zi_carr = sig.sosfilt(sos_carr, squared, zi=zi_carr)

    # Normalise carrier to unit amplitude so it doesn't scale L-R level
    c_rms = float(np.sqrt(np.mean(carrier ** 2))) + 1e-12
    carrier_norm = carrier / (c_rms * np.sqrt(2.0))

    # 3. Demodulate L-R DSB-SC via synchronous detection
    dsb,  zi_diff = sig.sosfilt(sos_diff, x,    zi=zi_diff)
    demod          = dsb * carrier_norm
    lmr,  zi_dlpf = sig.sosfilt(sos_dlpf, demod, zi=zi_dlpf)

    # 4. De-emphasis
    lpr_de, zi_de_s = sig.lfilter(de_b, de_a, lpr, zi=zi_de_s)
    lmr_de, zi_de_d = sig.lfilter(de_b, de_a, lmr, zi=zi_de_d)

    # 5. Matrix to L and R channels
    L = np.clip(lpr_de + STEREO_GAIN * lmr_de, -1.0, 1.0)
    R = np.clip(lpr_de - STEREO_GAIN * lmr_de, -1.0, 1.0)

    # 6. Resample RATE → OUT_RATE and interleave as s16le stereo
    L48 = sig.resample_poly(L, UP, DOWN).astype(np.float32)
    R48 = sig.resample_poly(R, UP, DOWN).astype(np.float32)

    stereo = np.empty(len(L48) * 2, dtype=np.float32)
    stereo[0::2] = L48
    stereo[1::2] = R48

    return (stereo * 32767.0).astype(np.int16)


def main() -> None:
    stdin  = sys.stdin.buffer
    stdout = sys.stdout.buffer

    print(f"[fm-stereo] started: {RATE} Hz mono → {OUT_RATE} Hz stereo"
          f"  gain={STEREO_GAIN}  de-emph={DE_EMPH_TC*1e6:.0f} µs",
          file=sys.stderr)

    buf    = b''
    needed = CHUNK * 2   # 2 bytes per s16le sample

    while True:
        chunk = stdin.read(needed - len(buf))
        if not chunk:
            break
        buf += chunk
        if len(buf) < needed:
            continue
        pcm = np.frombuffer(buf[:needed], dtype=np.int16)
        buf = buf[needed:]
        try:
            out = process(pcm)
            stdout.write(out.tobytes())
            stdout.flush()
        except Exception as e:
            print(f"[fm-stereo] processing error: {e}", file=sys.stderr)


if __name__ == '__main__':
    main()
