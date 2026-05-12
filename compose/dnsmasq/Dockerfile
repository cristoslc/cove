FROM alpine:3.21
RUN apk add --no-cache dnsmasq
COPY cove.conf /etc/dnsmasq.d/cove.conf
ENTRYPOINT ["dnsmasq", "--no-daemon", "--conf-dir=/etc/dnsmasq.d"]
