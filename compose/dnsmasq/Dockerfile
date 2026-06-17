# Build stage: compile the DoH proxy from source.
# This avoids committing a platform-specific binary to the repo
# (Harbor principle: everything runs inside Cove, nothing on the host).
FROM golang:1.24-alpine AS builder
WORKDIR /src
COPY doh-proxy-src/ ./
RUN CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -o /doh-proxy .

# Runtime stage: dnsmasq + doh-proxy in one container.
# doh-proxy forwards DoH requests from iOS/Android clients to the
# local dnsmasq instance, enabling encrypted DNS for mobile devices
# that cannot use plain UDP port 5353.
FROM alpine:3.21
RUN apk add --no-cache dnsmasq
# Fallback config; overridden by volume mount in docker-compose.yml
COPY cove.conf /etc/dnsmasq.d/cove.conf
COPY --from=builder /doh-proxy /usr/local/bin/doh-proxy
# Run dnsmasq with a restart loop so DNS doesn't silently die if
# dnsmasq crashes. doh-proxy runs in the foreground as PID 1.
# If doh-proxy exits, the container restarts (restart: unless-stopped).
ENTRYPOINT ["sh", "-c", "while true; do dnsmasq --no-daemon --conf-dir=/etc/dnsmasq.d; echo 'dnsmasq exited, restarting in 1s'; sleep 1; done & doh-proxy -upstream 127.0.0.1:5353 -listen :8053"]