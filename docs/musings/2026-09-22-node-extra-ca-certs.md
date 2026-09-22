# Node.js never reads the OS trust store

2026-09-22 — sparked by issue #51 (Kepler/GitKraken daemon failing TLS against git.cove.local).

## Observation

Cove installs its root CA into the OS trust store (macOS System keychain,
Linux ca-certificates). Browsers, curl, git-over-ssh all work fine against
`*.cove` / `*.cove.local`. But Node.js doesn't read the OS trust store —
it ships its own bundled Mozilla CA list. Any Node CLI, Electron
main/daemon process, MCP server, or agent process making HTTPS calls into
Cove rejects the chain with `unable to verify the first certificate`.

Reproduced for real: Kepler's daemon swept providers against the GitLab
shim in front of Forgejo and every `fetch failed` traced back to plain
`node -e fetch(...)` failing TLS while the browser worked. Fixed only by
`launchctl setenv NODE_EXTRA_CA_CERTS <rootCA.pem>` + relaunch.

## Half-formed thoughts

- `NODE_EXTRA_CA_CERTS` is the answer for Node, but it's per-process env,
  and `launchctl setenv` doesn't survive reboot. Durable per-app env
  belongs in the app's packaging (launchd plist, systemd unit, Electron
  main), not in Cove. Cove's job is to make the CA reachable and the fix
  discoverable.
- We already serve the CA at `/config/ca` with a stable filename
  (`cove-root-ca.pem` via Content-Disposition), and the host-side copy
  lives at `~/Documents/cove-data/certs/rootCA.pem`. So no new endpoint is
  needed — the gap is purely that nothing tells a Node user what to do.
- There's a deeper question lurking: could Cove do more? E.g. an
  installable per-user env shim, or a `.npmrc`-style convention. But
  that's over-engineering for now — the OS-store install path already
  exists for people who want durability, and Node-specific trust is one
  env var away.
- Latent vs urgent: most Cove consumers today are browsers/curl/git-ssh,
  so this is a documentation gap, not a code gap. But agent/MCP tooling is
  increasingly Node-based, and every future one hits this on day one.
- Durable alternative worth documenting alongside: macOS
  `security add-trusted-cert`, Linux `update-ca-certificates`. Both make
  Node trust moot for hosts that prefer OS-store durability over per-app
  env.

## Descendent

Crystallized into a plan: document Node/Electron trust on the ca.cove
config page (`compose/nginx/config.html.j2`) with the env-var fix, the
CA's stable paths, the durable OS-store alternative, and the launchctl
caveat. See issue #51 and the plan under `docs/plans/`.