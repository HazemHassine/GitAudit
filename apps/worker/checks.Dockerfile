# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS node
FROM ghcr.io/astral-sh/uv:0.8.22 AS uv
FROM ghcr.io/gitleaks/gitleaks:v8.24.2 AS gitleaks
FROM rhysd/actionlint:1.7.7 AS actionlint
FROM hadolint/hadolint:v2.14.0 AS hadolint
FROM docker:27-cli AS docker
FROM python:3.12-slim
# checkov:skip=CKV_DOCKER_3:Disposable check containers need workspace ownership; runtime drops every capability and has no host mounts or credentials.
# checkov:skip=CKV_DOCKER_2:Ephemeral command image; worker records process exit and enforces deadlines.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=gitleaks /usr/bin/gitleaks /usr/local/bin/gitleaks
COPY --from=actionlint /usr/local/bin/actionlint /usr/local/bin/actionlint
COPY --from=hadolint /bin/hadolint /usr/local/bin/hadolint
COPY --from=docker /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx && \
    pip install --no-cache-dir ruff==0.12.12 pip-audit==2.9.0 build==1.3.0 && \
    mkdir /workspace
COPY check_support.py /opt/gitaudit/check_support.py
WORKDIR /workspace
CMD ["python", "--version"]
