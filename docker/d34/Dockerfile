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
    PIP_INDEX_URL=https://pypi.org/simple \
    PIP_NO_CACHE_DIR=1 \
    PIP_RETRIES=10 \
    PIP_TIMEOUT=120 \
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

# D-34 is a headless worker.  Installing either upstream project with its full
# dependency set also installs JupyterLab, Streamlit, Selenium, AzureML and
# other interactive/demo stacks that this bounded research path never imports.
# Keep the real pinned upstream source, but install only the runtime packages
# exercised by versions/LLM/embedding/Qlib data/backtest/Docker-child smokes.
RUN python -m pip install --upgrade "pip==25.2" "setuptools==80.9.0" "wheel==0.45.1" \
    && python -m pip install \
       "setuptools-scm==9.2.2" \
       "cython==3.2.4" \
       "numpy==1.26.4" \
       "pandas==2.3.3" \
       "pyarrow==24.0.0" \
       "scipy==1.17.1" \
       "pydantic==2.12.5" \
       "pydantic-settings==2.14.2" \
       "pyyaml==6.0.3" \
       "filelock==3.32.2" \
       "redis==8.1.0" \
       "dill==0.4.1" \
       "fire==0.7.1" \
       "ruamel.yaml==0.19.1" \
       "python-redis-lock==4.0.1" \
       "tqdm==4.70.0" \
       "pymongo==4.17.0" \
       "loguru==0.7.3" \
       "joblib==1.5.3" \
       "litellm==1.96.0" \
       "openai==2.53.0" \
       "tiktoken==0.13.0" \
       "pytz==2026.2" \
       "rich==15.0.0" \
       "python-dotenv==1.2.2" \
       "docker==7.2.0" \
    && SETUPTOOLS_SCM_PRETEND_VERSION_FOR_RDAGENT=0.8.0.dev0 \
       python -m pip install --no-build-isolation --no-deps /opt/qlib /opt/rdagent

# qlib.init imports its workflow tracker even for a local file provider. The
# skinny distribution supplies that exact mlflow client surface without the
# serving/UI stack that the headless worker does not use.
RUN python -m pip install \
       "mlflow-skinny==3.1.4" \
       "gym==0.26.2" \
       "cvxpy==1.7.5" \
       "fuzzywuzzy==0.18.0" \
       "psutil==7.2.2"

# Pin Platform's remaining direct/runtime dependencies too. The image digest
# must not change because a later build resolves a newer permissive pyproject
# range from PyPI.
RUN python -m pip install \
       "duckdb==1.5.5" \
       "futu-api==10.9.6908" \
       "typer==0.27.1" \
       "simplejson==4.1.1" \
       "pycryptodome==3.23.0"

COPY pyproject.toml README.md /opt/platform/
COPY src /opt/platform/src
RUN python -m pip install --no-deps /opt/platform

# The pinned RD-Agent commit publishes metadata and a console script but its
# setuptools package list omits nested source packages. Keep the exact checked
# source tree importable instead of silently replacing it with another release.
ENV PYTHONPATH=/opt/rdagent

COPY docker/d34/container_entrypoint.py /opt/d34/container_entrypoint.py
RUN chmod 0755 /opt/d34/container_entrypoint.py \
    && mkdir -p /workspace/d34 /workspace/cache

WORKDIR /workspace/d34
ENTRYPOINT ["python", "/opt/d34/container_entrypoint.py"]
CMD ["versions"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD ["python", "/opt/d34/container_entrypoint.py", "versions"]
