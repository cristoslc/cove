# Muse: Web Terminal for Cove Management

## The idea

Add a web terminal tab to the Cove landing page (`cove.local`) with a "Restart Cove" button that pre-types `cove up` and switches to the terminal for interactive sudo password entry.

## Why

- Landing page shows when services are down
- Fixing requires terminal + sudo
- A web terminal in a tab closes the loop: see problem → click button → enter password → fixed
- No SSH, no separate terminal app needed

## How

- **Backend:** A small container (ttyd, wetty, or custom Go/Python) with:
  - WebSocket terminal server
  - `cove` CLI installed
  - Docker socket mounted (for `docker compose` commands)
  - Passwordless sudo for `cove up` only (via `/etc/sudoers.d/cove`)
- **Frontend:** xterm.js in a new tab on the landing page
- **Button:** "Restart Cove" → opens terminal tab, types `cove up`, user enters sudo password

## Security considerations

- Terminal access = full host access (Docker socket)
- Passwordless sudo for `cove up` is already a pattern we use (`compose/files/cove-sudoers`)
- Container should be opt-in (profiled service like litellm)
- Bind to localhost only, no external exposure

## Open questions

- ttyd vs wetty vs custom Go server with gorilla/websocket + os/exec
- Should the terminal container be part of the core stack or a separate profile?
- How to handle the "switch to terminal tab" UX — open new window? Switch tab in-page?
- Should the terminal persist across page reloads (session management)?
