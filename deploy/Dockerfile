# Astro Canvas lab server (design 4.3 tier 3, 12).
#
# Three stages so the runtime image carries neither Node nor a build toolchain:
#   1. web     - pnpm builds the SPA
#   2. wheel   - uv copies the SPA into the package and builds both wheels
#   3. runtime - uv installs those wheels (plus the packs) into /opt/venv
#
# Tooling rule (CONTRIBUTING): pnpm for the frontend, uv for Python, and nothing else. There is
# no `pip` in this file, and `uv` stays in the runtime image on purpose -- it is what the pack
# manager runs, and `find_uv` looks next to the interpreter first, so no configuration is needed.

# --- 1. the single-page app ---------------------------------------------------------------------
FROM node:22-bookworm-slim AS web
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
RUN corepack enable
WORKDIR /src/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml ./
COPY frontend/scripts ./scripts
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm run build-only

# --- 2. the wheels ------------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:0.11-python3.12-bookworm-slim AS wheel
WORKDIR /src
COPY backend/ backend/
COPY packs/ packs/
COPY scripts/ scripts/
COPY README.md LICENSE ./
COPY --from=web /src/frontend/dist/ frontend/dist/
RUN uv run --directory backend --no-project --with hatchling \
      python ../scripts/copy_static.py \
 && uv build backend/sdk --out-dir /dist \
 && uv build backend --out-dir /dist \
 && uv build packs/core --out-dir /dist \
 && uv build packs/rbcodes --out-dir /dist

# --- 3. the runtime -----------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# Astropy and pyarrow ship wheels; only libgomp (numpy/scipy threading) and CA certificates
# are needed at run time. rbcodes' matplotlib-based modules need MPLBACKEND=Agg.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

RUN uv venv /opt/venv
COPY --from=wheel /dist /tmp/dist
RUN uv pip install --no-cache /tmp/dist/*.whl \
 && uv pip install --no-cache "astro-canvas[users]" --no-deps \
 && rm -rf /tmp/dist \
 # ``find_uv`` prefers a binary next to the interpreter, so the manager needs no configuration.
 && cp /usr/local/bin/uv /opt/venv/bin/uv

# A non-root user owns /data; the pack manager writes to /opt/venv, so that is theirs too.
RUN useradd --create-home --uid 10001 canvas \
 && mkdir -p /data/users /data/shared /home/canvas/.config \
 && chown -R canvas:canvas /data /opt/venv /home/canvas
USER canvas

ENV MPLBACKEND=Agg \
    QT_QPA_PLATFORM=offscreen \
    ASTRO_CANVAS_HOST=0.0.0.0 \
    ASTRO_CANVAS_PORT=8765 \
    ASTRO_CANVAS_AUTH=users \
    ASTRO_CANVAS_WORKSPACE=/data \
    ASTRO_CANVAS_USERS_DIR=/data/users \
    ASTRO_CANVAS_SHARED_DIR=/data/shared \
    ASTRO_CANVAS_CONFIG_DIR=/data/config \
    ASTRO_CANVAS_PACK_SECURITY=strict \
    ASTRO_CANVAS_PROCESS_POOL=true

VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=4).status == 200 else 1)"]

# ``serve`` reads every setting above from the environment. ``--auth users`` is what makes
# ``--host 0.0.0.0`` acceptable at all (server/guard.py).
ENTRYPOINT ["astro-canvas"]
CMD ["serve"]
