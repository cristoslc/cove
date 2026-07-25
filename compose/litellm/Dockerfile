FROM python:3.13-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates nodejs npm \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "litellm[proxy]==1.84.0" prisma

# Generate Prisma client and download query engine binaries
RUN prisma generate --schema=/usr/local/lib/python3.13/site-packages/litellm/proxy/schema.prisma

FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates libatomic1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Prisma Python client hardcodes binary paths to /root/.cache/prisma-python/...
# Make /root accessible and copy binaries with litellm ownership
RUN chmod 755 /root
COPY --from=builder --chown=litellm:litellm /root/.cache/prisma-python /root/.cache/prisma-python

RUN addgroup --system --gid 1000 litellm && \
    adduser --system --uid 1000 --ingroup litellm --home /home/litellm litellm && \
    mkdir -p /app /var/log/litellm /home/litellm && \
    chown -R litellm:litellm /app /var/log/litellm /home/litellm && \
    chown -R litellm:litellm /usr/local/lib/python3.13/site-packages/litellm/proxy/_experimental

USER litellm
ENV HOME=/home/litellm
WORKDIR /app

EXPOSE 4000

ENTRYPOINT ["litellm"]
CMD ["--config", "/app/config.yaml", "--port", "4000", "--host", "0.0.0.0"]