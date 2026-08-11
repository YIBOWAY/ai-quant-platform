# syntax=docker/dockerfile:1.7
FROM python:3.11-slim-bookworm@sha256:d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3

ARG RDAGENT_COMMIT=274e274d5dbb72cc2ea139d1a7c93d73ce9b1198
ARG QLIB_COMMIT=da920b7f954f48ab1bb64117c976710de198373e
ARG RDAGENT_TARBALL_SHA256=c3af9e4f153a5ef407deaa2a04b281be62d3fd7c380e2ca647d30cec5b7bc07c
ARG QLIB_TARBALL_SHA256=016ec8f5d415e4b4251412e60a395154332cb2db0239c20a522b04de6198131f

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

RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get install -y --no-install-recommends \
       build-essential ca-certificates curl git libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN curl --fail --location --retry 8 --retry-all-errors \
        --output /tmp/qlib.tar.gz \
        "https://codeload.github.com/microsoft/qlib/tar.gz/${QLIB_COMMIT}" \
    && echo "${QLIB_TARBALL_SHA256}  /tmp/qlib.tar.gz" | sha256sum --check \
    && mkdir -p /opt/qlib \
    && tar --extract --gzip --file /tmp/qlib.tar.gz \
       --directory /opt/qlib --strip-components=1 \
    && echo "${QLIB_COMMIT}" > /opt/qlib/.hqa-upstream-commit \
    && rm /tmp/qlib.tar.gz

RUN curl --fail --location --retry 8 --retry-all-errors \
        --output /tmp/rdagent.tar.gz \
        "https://codeload.github.com/microsoft/RD-Agent/tar.gz/${RDAGENT_COMMIT}" \
    && echo "${RDAGENT_TARBALL_SHA256}  /tmp/rdagent.tar.gz" | sha256sum --check \
    && mkdir -p /opt/rdagent \
    && tar --extract --gzip --file /tmp/rdagent.tar.gz \
       --directory /opt/rdagent --strip-components=1 \
    && echo "${RDAGENT_COMMIT}" > /opt/rdagent/.hqa-upstream-commit \
    && rm /tmp/rdagent.tar.gz

RUN python -m pip install --upgrade "pip==25.2" "setuptools==80.9.0" wheel \
    && python -m pip install /opt/qlib \
    && python -m pip install /opt/rdagent

COPY pyproject.toml README.md /opt/platform/
COPY src /opt/platform/src
RUN python -m pip install /opt/platform

COPY docker/d34/container_entrypoint.py /opt/d34/container_entrypoint.py
RUN chmod 0755 /opt/d34/container_entrypoint.py \
    && mkdir -p /workspace/d34 /workspace/cache

WORKDIR /workspace/d34
ENTRYPOINT ["python", "/opt/d34/container_entrypoint.py"]
CMD ["versions"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD ["python", "/opt/d34/container_entrypoint.py", "versions"]
