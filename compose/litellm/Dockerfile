FROM python:3.13-slim AS builder

RUN pip install --no-cache-dir \
    litellm==1.84.0 \
    headroom-ai[all]

FROM python:3.13-slim

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY config.yaml /app/config.yaml

RUN addgroup --system --gid 1000 litellm && \
    adduser --system --uid 1000 --ingroup litellm litellm && \
    mkdir -p /var/log/litellm && \
    chown -R litellm:litellm /app /var/log/litellm

USER litellm
WORKDIR /app

EXPOSE 4000

ENTRYPOINT ["litellm"]
CMD ["--config", "/app/config.yaml", "--port", "4000", "--host", "127.0.0.1"]
