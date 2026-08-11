# syntax=docker/dockerfile:1.7
FROM python:3.11-slim-bookworm@sha256:d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3

ARG RDAGENT_COMMIT=274e274d5dbb72cc2ea139d1a7c93d73ce9b1198
ARG QLIB_COMMIT=da920b7f954f48ab1bb64117c976710de198373e

LABEL org.opencontainers.image.title="HQA D-34 RD-Agent + Qlib runtime" \
      hqa.d34.rdagent.commit="${RDAGENT_COMMIT}" \
      hqa.d34.qlib.commit="${QLIB_COMMIT}" \
      hqa.d34.execution.scope="paper_only"

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    D34_RDAGENT_ROOT=/opt/rdagent \
    D34_QLIB_ROOT=/opt/qlib \
    D34_WORKSPACE=/workspace/d34

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential ca-certificates curl git libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN git init /opt/qlib \
    && git -C /opt/qlib remote add origin https://github.com/microsoft/qlib.git \
    && git -C /opt/qlib fetch --depth 1 origin "${QLIB_COMMIT}" \
    && git -C /opt/qlib checkout --detach FETCH_HEAD \
    && test "$(git -C /opt/qlib rev-parse HEAD)" = "${QLIB_COMMIT}"

RUN git init /opt/rdagent \
    && git -C /opt/rdagent remote add origin https://github.com/microsoft/RD-Agent.git \
    && git -C /opt/rdagent fetch --depth 1 origin "${RDAGENT_COMMIT}" \
    && git -C /opt/rdagent checkout --detach FETCH_HEAD \
    && test "$(git -C /opt/rdagent rev-parse HEAD)" = "${RDAGENT_COMMIT}"

RUN python -m pip install --upgrade "pip==25.2" "setuptools==80.9.0" wheel \
    && python -m pip install /opt/qlib \
    && python -m pip install /opt/rdagent

COPY docker/d34/container_entrypoint.py /opt/d34/container_entrypoint.py
RUN chmod 0755 /opt/d34/container_entrypoint.py \
    && mkdir -p /workspace/d34 /workspace/cache

WORKDIR /workspace/d34
ENTRYPOINT ["python", "/opt/d34/container_entrypoint.py"]
CMD ["versions"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD ["python", "/opt/d34/container_entrypoint.py", "versions"]
