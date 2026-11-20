# Observe-only secrets check in front of the Bifrost gateway.
#
# Two stages, both digest-pinned. The build stage links the gitleaks rule engine
# into the binary as a Go library — the container never spawns a `gitleaks`
# process, which is the 246 ms-per-request failure mode the spike measured. The
# runtime stage carries only a static binary: no shell, no package manager, no
# writable rootfs.
#
# The image carries NO ruleset on purpose. The rules are the repository's one
# `.gitleaks.toml`, mounted read-only from the data root at run time
# (`${COVE_DATA_ROOT}/secrets-guard/gitleaks.toml`, seeded from the wheel by
# `cove secrets-guard up`). One image works with any ruleset, a rules change
# needs no rebuild, and an operator can read the exact rules in force instead of
# trusting what a layer was built with.
FROM golang:1.25.4-alpine@sha256:d3f0cf7723f3429e3f9ed846243970b20a2de7bae6a5b66fc5914e228d831bbb AS build

WORKDIR /src

# Module download is its own layer so a source edit does not refetch the graph.
COPY go.mod go.sum ./
RUN go mod download

COPY . ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/secrets-guard .

FROM gcr.io/distroless/static-debian12:nonroot@sha256:afa5c872c891853ca7fcf1f12c3edb23f7eeef36189728842dd51042ff57f7ab

COPY --from=build /out/secrets-guard /usr/local/bin/secrets-guard

USER nonroot:nonroot

EXPOSE 8080

# No arguments: serve. `healthcheck` and `scan` are the other subcommands.
ENTRYPOINT ["/usr/local/bin/secrets-guard"]
