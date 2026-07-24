# Horizon sidecar — clones upstream at a pinned SHA; does not vendor source
# into the platform runtime. Secrets arrive only via compose env_file.
FROM python:3.12-slim

ARG HORIZON_REF=1e2fdc7ccb177f33c59aef2082c4093e1e82b22c

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/horizon

# Clone pinned upstream. Build requires network; runtime does not bake secrets.
RUN git clone --filter=blob:none https://github.com/Thysrael/Horizon.git . \
    && git checkout "${HORIZON_REF}" \
    && rm -rf .git

# uv for upstream dependency resolution (matches Horizon's preferred toolchain).
RUN pip install --no-cache-dir uv \
    && uv sync --no-dev

COPY export_run.py /opt/bin/export_run.py
COPY entrypoint.sh /opt/bin/entrypoint.sh
COPY config.example.json /opt/horizon/config.example.json
RUN chmod +x /opt/bin/entrypoint.sh \
    && mkdir -p /inbox /config \
    # Keep a seed config outside /opt/horizon/data so a named volume mount
    # cannot hide the image example on first boot.
    && cp /opt/horizon/config.example.json /opt/config.example.json

# Runtime mounts:
#   /inbox  <- ./data/horizon_inbox
#   /config <- ./data/horizon_config (ro) containing config.json
#   volume  <- /opt/horizon/data (upstream summaries; may be empty on first boot)
ENV HORIZON_INBOX=/inbox \
    HORIZON_DATA_DIR=/opt/horizon/data \
    HORIZON_RUN_INTERVAL_SECONDS=21600 \
    HORIZON_HOURS=24 \
    PYTHONUNBUFFERED=1

# No Postgres client, no QS_* env defaults, no secrets baked in.
ENTRYPOINT ["/opt/bin/entrypoint.sh"]
