FROM node:24-bookworm-slim

ARG BB_APP_VERSION=0.43.4

ENV BB_DATA_DIR=/data
ENV BB_SERVER_BIND_HOST=0.0.0.0
ENV BB_SERVER_PORT=38886

RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates procps \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g --allow-scripts=better-sqlite3,node-pty,@parcel/watcher bb-app@${BB_APP_VERSION}

RUN mkdir -p /data

EXPOSE 38886

ENTRYPOINT ["bb-app"]
CMD ["--data-dir", "/data"]
