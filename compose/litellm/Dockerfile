FROM python:3.13-slim AS builder

RUN pip install --no-cache-dir "litellm[proxy]==1.84.0"

FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

RUN addgroup --system --gid 1000 litellm && \
    adduser --system --uid 1000 --ingroup litellm litellm && \
    mkdir -p /app /var/log/litellm && \
    chown -R litellm:litellm /app /var/log/litellm

USER litellm
WORKDIR /app

EXPOSE 4000

ENTRYPOINT ["litellm"]
CMD ["--config", "/app/config.yaml", "--port", "4000", "--host", "0.0.0.0"]
