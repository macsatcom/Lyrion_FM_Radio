# FM Radio Daemon — Docker image
# Includes: rtl-sdr-blog (built from source), redsea (built from source), ffmpeg, Icecast2, Python3
# rtl-sdr-blog fork adds support for RTL-SDR Blog V4 dongles.
#
# Build context must be the repository root:
#   docker build -f docker/Dockerfile -t fm-radio .
#
# Normally you use docker-compose instead — see docker-compose.yml.

FROM debian:bookworm-slim

# ── Runtime dependencies ──────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-numpy \
        python3-scipy \
        ffmpeg \
        icecast2 \
        libusb-1.0-0 \
        libsndfile1 \
        libliquid1 \
        gettext-base \
    && rm -rf /var/lib/apt/lists/*

# ── Build rtl-sdr-blog from source ────────────────────────────────────────────
# Uses the RTL-SDR Blog fork which adds support for RTL-SDR Blog V4 dongles.
# Installs rtl_fm and librtlsdr to /usr/local.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates cmake build-essential libusb-1.0-0-dev \
    && git clone --depth 1 https://github.com/rtlsdrblog/rtl-sdr-blog.git /tmp/rtl-sdr-blog \
    && cmake -S /tmp/rtl-sdr-blog -B /tmp/rtl-sdr-blog/build \
        -DINSTALL_UDEV_RULES=OFF \
        -DDETACH_KERNEL_DRIVER=ON \
    && make -C /tmp/rtl-sdr-blog/build -j$(nproc) \
    && make -C /tmp/rtl-sdr-blog/build install \
    && ldconfig \
    && rm -rf /tmp/rtl-sdr-blog \
    && apt-get purge -y git cmake build-essential libusb-1.0-0-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# ── Build redsea from source ──────────────────────────────────────────────────
# windytan/redsea — FM RDS decoder; reads rtl_fm output and emits JSON lines.
# Requires --recurse-submodules for the nlohmann/json submodule.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates meson ninja-build build-essential pkg-config \
        libsndfile1-dev libliquid-dev \
    && git clone --depth 1 --recurse-submodules https://github.com/windytan/redsea.git /tmp/redsea \
    && cd /tmp/redsea \
    && meson setup --buildtype=release build \
    && ninja -C build \
    && (install -m 755 build/src/redsea /usr/local/bin/redsea 2>/dev/null || install -m 755 build/redsea /usr/local/bin/redsea) \
    && rm -rf /tmp/redsea \
    && apt-get purge -y git meson ninja-build build-essential pkg-config libsndfile1-dev libliquid-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# ── Application files ─────────────────────────────────────────────────────────
COPY daemon/fm-daemon.py         /usr/local/bin/fm-daemon.py
COPY daemon/fm-stereo.py         /usr/local/bin/fm-stereo.py
COPY docker/icecast.xml.template /etc/icecast.xml.template
COPY docker/entrypoint.sh        /entrypoint.sh

RUN chmod +x /usr/local/bin/fm-daemon.py /usr/local/bin/fm-stereo.py /entrypoint.sh

# 8080 = FM Daemon HTTP API, 8000 = Icecast stream
EXPOSE 8080 8000

ENTRYPOINT ["/entrypoint.sh"]
