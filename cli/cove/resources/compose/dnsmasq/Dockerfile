FROM alpine:3.21
RUN apk add --no-cache dnsmasq
# Config is provided at runtime via volume mount from $COVE_DATA_ROOT/dnsmasq/cove.conf.
ENTRYPOINT ["dnsmasq", "--no-daemon", "--conf-dir=/etc/dnsmasq.d"]
