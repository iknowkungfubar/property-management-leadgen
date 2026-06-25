# ─────────────────────────────────────────────────────────────────────────────
# Dockerfile — leadgen-sidecar (headless Python sidecar)
#
# Multi-stage build: the builder stage installs Python deps and downloads the
# Playwright Chromium browser; the runtime stage keeps only what is needed at
# run time (no gcc, pip cache, or build tools).
#
# Usage:
#   docker build -t leadgen-sidecar .
#   docker run -i leadgen-sidecar         # interactive stdin/stdout IPC
#   echo '{"id":"1","method":"ping","params":{}}' | docker run -i leadgen-sidecar
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: builder ────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build

# Install system libraries required _during_ the build so that
# `playwright install chromium --with-deps` can install the browser and any
# extra distro packages it discovers, AND so pip can compile any native wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Playwright runtime deps (needed here so --with-deps works)
    libnss3 \
    libnspr4 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata first (Docker layer caching — these change rarely)
COPY pyproject.toml ./

# Copy source so `pip install .` can resolve the package
COPY src/ ./src/

# Install all project dependencies (playwright, pydantic, httpx, etc.) and the
# project itself into site-packages.
RUN pip install --no-cache-dir .

# Download the Chromium browser binary that Playwright will use.
# The --with-deps flag installs any extra distro packages detected for this
# browser version; they are already satisfied by the apt list above.
RUN python3 -m playwright install chromium --with-deps

# ── Stage 2: runtime ───────────────────────────────────────────────────────
FROM python:3.13-slim

# ── Create non-root user ──────────────────────────────────────────────────────
RUN groupadd -r leadgen && useradd -r -g leadgen -d /home/leadgen -s /sbin/nologin leadgen

# ── Runtime system libraries ──────────────────────────────────────────────────
# Only the shared libraries Playwright needs at runtime — no gcc, no build deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libnspr4 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    # procps provides pgrep, used by the HEALTHCHECK
    procps \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── Copy Python environment from builder ─────────────────────────────────────
COPY --from=builder /usr/local/lib/python3.13/site-packages/ /usr/local/lib/python3.13/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# ── Copy Playwright browser bundle ───────────────────────────────────────────
# Place it under a system-managed path so we can set ownership for the
# non-root user.  The PLAYWRIGHT_BROWSERS_PATH env var (set below) tells
# Playwright where to find it.
RUN mkdir -p /usr/lib/leadgen/ms-playwright
COPY --from=builder /root/.cache/ms-playwright/ /usr/lib/leadgen/ms-playwright/
RUN chown -R leadgen:leadgen /usr/lib/leadgen/

# ── Copy application source ──────────────────────────────────────────────────
COPY runner.py /app/runner.py
COPY src/     /app/src/

WORKDIR /app

# ── Data directory ───────────────────────────────────────────────────────────
RUN mkdir -p /home/leadgen/.leadgen && \
    chown -R leadgen:leadgen /home/leadgen /app && \
    chmod 755 /app /app/runner.py

USER leadgen

# ── Environment ──────────────────────────────────────────────────────────────
ENV LEADGEN_DB_PATH=/home/leadgen/.leadgen/leadgen.db \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/usr/lib/leadgen/ms-playwright

# ── Metadata ──────────────────────────────────────────────────────────────────
EXPOSE 0
#   No ports exposed — the sidecar is a stdin/stdout JSON-RPC process.
#   Container orchestration (Kubernetes, Docker Compose) can still exec into
#   the container for health checks or use PID-based liveness probes.

# ── Healthcheck ──────────────────────────────────────────────────────────────
# Verifies the Python sidecar process is alive.  A true JSON-RPC ping would
# require the sidecar to expose a socket endpoint — that is a future feature.
# For now, pgrep confirms the process tree is intact; Docker/K8s restart
# policies handle the case where the process has crashed.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD pgrep -f "python.*runner" > /dev/null 2>&1 || exit 1

# ── Default command ──────────────────────────────────────────────────────────
CMD ["python3", "/app/runner.py"]
