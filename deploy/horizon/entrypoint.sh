#!/bin/sh
# Horizon sidecar loop: run upstream CLI, export inbox contract, sleep.
# Never connects to Postgres. LLM keys come from env_file only.
set -eu

INTERVAL="${HORIZON_RUN_INTERVAL_SECONDS:-21600}"
HORIZON_DATA="${HORIZON_DATA_DIR:-/opt/horizon/data}"
INBOX="${HORIZON_INBOX:-/inbox}"
HOURS="${HORIZON_HOURS:-24}"

# Optional host-mounted config → upstream expected path.
# Note: a named volume on HORIZON_DATA hides image-baked data/; seed from
# /opt/config.example.json (copied outside data/) when nothing else is present.
mkdir -p "${HORIZON_DATA}"
if [ -f /config/config.json ]; then
  # Prefer symlink so edits on the host are visible without rebuild.
  ln -sfn /config/config.json "${HORIZON_DATA}/config.json"
elif [ ! -f "${HORIZON_DATA}/config.json" ]; then
  if [ -f /opt/config.example.json ]; then
    cp /opt/config.example.json "${HORIZON_DATA}/config.json"
    echo "entrypoint: seeded ${HORIZON_DATA}/config.json from image example" >&2
  elif [ -f /opt/horizon/config.example.json ]; then
    cp /opt/horizon/config.example.json "${HORIZON_DATA}/config.json"
    echo "entrypoint: seeded ${HORIZON_DATA}/config.json from deploy example" >&2
  else
    echo "entrypoint: WARNING no config.json available under /config or examples" >&2
  fi
fi

cd /opt/horizon

while true; do
  echo "entrypoint: starting horizon --hours ${HOURS} at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  # Log failures but continue to export whatever artifacts exist.
  if ! uv run horizon --hours "${HOURS}"; then
    echo "entrypoint: horizon CLI failed (continuing to export)" >&2
  fi

  echo "entrypoint: exporting inbox from ${HORIZON_DATA} -> ${INBOX}"
  if ! python /opt/bin/export_run.py --horizon-data "${HORIZON_DATA}" --inbox "${INBOX}"; then
    echo "entrypoint: export_run failed (no READY written)" >&2
  fi

  echo "entrypoint: sleeping ${INTERVAL}s"
  sleep "${INTERVAL}"
done
