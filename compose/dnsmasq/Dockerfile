FROM alpine:3.21
RUN apk add --no-cache dnsmasq
# Fallback config; overridden by volume mount in docker-compose.yml
COPY cove.conf /etc/dnsmasq.d/cove.conf
COPY doh-proxy /usr/local/bin/doh-proxy
ENTRYPOINT ["sh", "-c", "dnsmasq --no-daemon --conf-dir=/etc/dnsmasq.d & doh-proxy -upstream 127.0.0.1:5353 -listen :8053"]
