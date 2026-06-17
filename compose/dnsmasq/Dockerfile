FROM alpine:3.21
RUN apk add --no-cache dnsmasq
# Fallback config; overridden by volume mount in docker-compose.yml
COPY cove.conf /etc/dnsmasq.d/cove.conf
ENTRYPOINT ["dnsmasq", "--no-daemon", "--conf-dir=/etc/dnsmasq.d"]
