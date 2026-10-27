# Egress sinkhole for the bifrost profile (DNS allowlist choke point).
# A minimal dnsmasq runner: the allowlist lives in dnsmasq.conf (git-tracked,
# seeded first-boot-only to the data root), and the container only re-mounts
# that single file read-only. Publishing no ports; the gateway container
# reaches it by static IP on the dedicated bifrost-egress network.
FROM alpine:3.23.7@sha256:ff7f0c727dd796aa36787bfcd9a64bf35a6ce72a73451b3359fde849b6703d63

# Upgrade the pinned distro image for security patches, then install the
# exact dnsmasq package version shipped by that distro release, so rebuilds
# are reproducible.
RUN apk upgrade --no-cache && apk add --no-cache dnsmasq=2.91-r1

# Validate the allowlist at build time: a config dnsmasq --test refuses must
# fail the build, not the egress boundary at container start.
COPY dnsmasq.conf /etc/dnsmasq.d/bifrost.conf
RUN dnsmasq --test -C /etc/dnsmasq.d/bifrost.conf

# DNS listener; compose publishes nothing — only the bifrost service resolves
# through this container. The rootfs is read-only, so no pidfile is written
# at all: an empty --pid-file path is dnsmasq's documented "no pid file"
# form (2.78+). That keeps zero writable mounts and avoids the default /run
# pidfile write (which is what crash-looped the sink).
EXPOSE 53/udp
CMD ["dnsmasq", "-k", "-C", "/etc/dnsmasq.d/bifrost.conf", "--pid-file="]