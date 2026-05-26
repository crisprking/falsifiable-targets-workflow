FROM python:3.12-slim AS builder
ARG FT_REF=v1.4.1
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN git clone --depth 1 --branch ${FT_REF} https://github.com/crisprking/falsifiable-targets.git . \
    && pip install --no-cache-dir --user .

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tini ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 ft
COPY --from=builder /root/.local /home/ft/.local
COPY --from=builder /build/sentinels /home/ft/.local/lib/python3.12/site-packages/sentinels
COPY --from=builder /build/claims /home/ft/.local/lib/python3.12/site-packages/claims
USER ft
ENV PATH="/home/ft/.local/bin:${PATH}" PYTHONUNBUFFERED=1
WORKDIR /work
HEALTHCHECK --interval=30s --timeout=10s CMD ft-smoke || exit 1
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["ft-audit", "--help"]
