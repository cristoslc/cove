# shellcheck shell=zsh
# ── OpenCode session manager ────────────────────────────────────────
#
# Source this file from your ~/.zshrc to get oc-tui, oc-restart, oc-web,
# and oc-direct.  The server runs inside a dedicated tmux session behind a
# Caddy reverse proxy that adds HTTP basic auth so the web UI is safe to
# expose on localhost.
#
# Dependencies: tmux, caddy, jq, sqlite3
# Optional:     1Password CLI (op) — if absent, set creds via env vars
#
# Environment variables (optional):
#   OPENCODE_SERVER_USERNAME / OPENCODE_SERVER_PASSWORD   skip 1Password
#   _OC_SERVE_PORT / _OC_CADDY_PORT                       override ports
#   _OC_RESTART_THRESHOLD_MS                              session age window
#   _OC_STALE_LOCK_THRESHOLD                              lockdir staleness (s)
#   _OC_LOG_MAX_SIZE                                      max log size before rotation (bytes)
#   _OC_MAX_PROJECT_CLIMB                                 directory climb limit

# ── Platform detection ──────────────────────────────────────────────

_OC_OS="$(uname -s)"
if [[ "$_OC_OS" == "Darwin" ]]; then
  _OC_OPEN="open"
  _OC_STAT_SIZE_FLAG="-f %z"
  _OC_STAT_MTIME_FLAG="-f %m"
else
  _OC_OPEN="xdg-open"
  _OC_STAT_SIZE_FLAG="-c %s"
  _OC_STAT_MTIME_FLAG="-c %Y"
fi

# ── Tunable constants ───────────────────────────────────────────────
#
# _OC_CACHE_TTL=900         15 min — balances freshness against
#                            1Password CLI call frequency
# _OC_SERVE_PORT=4095       internal opencode serve port
# _OC_CADDY_PORT=4096       public Caddy reverse-proxy port; chose
#                            adjacent ports to avoid conflicts with
#                            common dev ports (3000, 4000, 5000, 8000)
# _OC_RESTART_THRESHOLD_MS=300000  5 min — typical session time-to-live
#                            window; sessions updated within this window
#                            get a continuation prompt, older ones are
#                            repaired silently
# _OC_STALE_LOCK_THRESHOLD=60       1 min — window after which an
#                            orphaned lockdir is considered stale; set
#                            above typical SIGKILL recovery time
# _OC_LOG_MAX_SIZE=10485760        10 MB — logs are rotated during
#                            cold start if they exceed this size
# _OC_MAX_PROJECT_CLIMB=6          max dirs to walk up from $PWD to
#                            find a .git dir for project-name detection
# _OC_SERVE_START_TIMEOUT=10       max seconds to wait for opencode
#                            serve to respond to health checks
# _OC_CADDY_START_TIMEOUT=5        max seconds to wait for caddy
#                            to respond to health checks
# _OC_LOCK_RETRY_MS=0.5           sleep between lockdir acquisition
#                            retries
# _OC_LOCK_MAX_RETRIES=120        max lockdir acquisition retries
#                            (60s at 0.5s intervals)
# _OC_TMUX_ERROR_SLEEP=30         seconds to keep tmux pane visible
#                            after component exits with error
# _OC_BCRYPT_COST=10              htpasswd bcrypt cost factor —
#                            balances security vs startup latency

_OC_CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/opencode"
_OC_CACHE_FILE="$_OC_CACHE_DIR/creds"
_OC_CACHE_TTL=900
_OC_SERVE_PORT="${_OC_SERVE_PORT:-4095}"
_OC_CADDY_PORT="${_OC_CADDY_PORT:-4096}"
_OC_CADDYDIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
_OC_LOGDIR="${XDG_DATA_HOME:-$HOME/.local/share}/opencode/logs"
_OC_CADDY_HASH_FILE="$_OC_CACHE_DIR/caddy-hash"
_OC_CADDY_ENV_FILE="$_OC_CACHE_DIR/caddy.env"
_OC_SERVE_ENV_FILE="$_OC_CACHE_DIR/serve.env"
_OC_SERVER_SESSION="opencode-server"
_OC_RESTART_THRESHOLD_MS="${_OC_RESTART_THRESHOLD_MS:-300000}"
_OC_STALE_LOCK_THRESHOLD="${_OC_STALE_LOCK_THRESHOLD:-60}"
_OC_LOG_MAX_SIZE="${_OC_LOG_MAX_SIZE:-10485760}"
_OC_MAX_PROJECT_CLIMB="${_OC_MAX_PROJECT_CLIMB:-6}"
_OC_SERVE_START_TIMEOUT="${_OC_SERVE_START_TIMEOUT:-10}"
_OC_CADDY_START_TIMEOUT="${_OC_CADDY_START_TIMEOUT:-5}"
_OC_LOCK_RETRY_MS="${_OC_LOCK_RETRY_MS:-0.5}"
_OC_LOCK_MAX_RETRIES="${_OC_LOCK_MAX_RETRIES:-120}"
_OC_TMUX_ERROR_SLEEP="${_OC_TMUX_ERROR_SLEEP:-30}"
_OC_BCRYPT_COST="${_OC_BCRYPT_COST:-10}"

# ── Stat helpers (platform-portable) ─────────────────────────────────

_oc-stat-mtime() {
  local val
  val=$(stat "$_OC_STAT_MTIME_FLAG" "$1")
  echo "${val## }"
}

_oc-stat-size() {
  local val
  val=$(stat "$_OC_STAT_SIZE_FLAG" "$1")
  echo "${val## }"
}

# ── Credential helpers ──────────────────────────────────────────────

_oc-creds() {
  if [[ -n "${OPENCODE_SERVER_USERNAME:-}" && -n "${OPENCODE_SERVER_PASSWORD:-}" ]]; then
    _OC_USER="$OPENCODE_SERVER_USERNAME"
    _OC_PASS="$OPENCODE_SERVER_PASSWORD"
    return 0
  fi

  if ! command -v op &>/dev/null; then
    echo "1Password CLI (op) not found. Set OPENCODE_SERVER_USERNAME and OPENCODE_SERVER_PASSWORD instead." >&2
    return 1
  fi

  if [[ -f "$_OC_CACHE_FILE" ]]; then
    local now cache_mtime age
    now=$(date +%s)
    cache_mtime=$(_oc-stat-mtime "$_OC_CACHE_FILE" 2>/dev/null) || cache_mtime=0
    age=$(( now - cache_mtime ))
    if [[ $age -lt $_OC_CACHE_TTL ]]; then
      _OC_USER=""
      _OC_PASS=""
      IFS=$'\n' read -r _OC_USER _OC_PASS < "$_OC_CACHE_FILE"
      if [[ -n "$_OC_USER" && -n "$_OC_PASS" ]]; then
        return 0
      fi
    fi
  fi

  local username password
  if ! username=$(command op read "op://Private/OpenCode Server/username" 2>/dev/null); then
    echo "Failed to read username from 1Password. Run 'op signin' and check that 'OpenCode Server' item exists." >&2
    return 1
  fi
  username="${username//$'\n'/}"
  if [[ -z "$username" ]]; then
    echo "1Password returned empty username for 'OpenCode Server' item." >&2
    return 1
  fi
  if ! password=$(command op read "op://Private/OpenCode Server/password" 2>/dev/null); then
    echo "Failed to read password from 1Password.  Check the 'OpenCode Server' item in your Private vault." >&2
    return 1
  fi
  password="${password//$'\n'/}"
  if [[ -z "$password" ]]; then
    echo "1Password returned empty password for 'OpenCode Server' item." >&2
    return 1
  fi

  _OC_USER="$username"
  _OC_PASS="$password"
  mkdir -p "$_OC_CACHE_DIR"
  chmod 700 "$_OC_CACHE_DIR"
  printf '%s\n%s' "$username" "$password" > "$_OC_CACHE_FILE"
  chmod 600 "$_OC_CACHE_FILE"
}

_oc-ensure-creds() {
  if [[ -n "${_OC_USER:-}" && -n "${_OC_PASS:-}" ]]; then
    return 0
  fi
  _oc-creds
}

# Verify that a string is safe for SQLite ID interpolation: only
# alphanumerics, dashes, and underscores are allowed.  Used by
# _oc-repair-sessions-db as a guard before interpolating IDs into UPDATE
# statements.
_oc-valid-id() {
  [[ "$1" =~ ^[a-zA-Z0-9_-]+$ ]]
}

# ── Utility ─────────────────────────────────────────────────────────

_oc-project-name() {
  local dir="$PWD" i
  for (( i=1; i<=_OC_MAX_PROJECT_CLIMB; i++ )); do
    if [[ -d "$dir/.git" ]]; then
      command basename "$dir"
      return
    fi
    dir="$(command dirname "$dir")"
    if [[ "$dir" == "/" ]]; then break; fi
  done
  command basename "$PWD"
}

_oc-window-name() {
  local branch
  branch=$(command git -C "$PWD" rev-parse --abbrev-ref HEAD 2>/dev/null) || branch=$(command basename "$PWD")
  echo "$(command basename "$PWD"):$branch"
}

_oc-session-name() {
  echo "oc-tui | $(_oc-project-name)"
}

# ── Log helpers ─────────────────────────────────────────────────────

_oc-ensure-logs() {
  mkdir -p "$_OC_LOGDIR"
  chmod 700 "$_OC_LOGDIR"
}

# Rotate a log file if it exceeds _OC_LOG_MAX_SIZE.  Truncates the
# file in place.  Called from cold-start path before tmux panes are
# launched, and before caddy restart tee-appends.
_oc-rotate-log() {
  local logfile="$1"
  if [[ -f "$logfile" ]]; then
    local size
    size=$(_oc-stat-size "$logfile" 2>/dev/null) || size=0
    if (( size > _OC_LOG_MAX_SIZE )); then
      echo "warning: rotating $(command basename "$logfile") (${size} bytes exceeded ${_OC_LOG_MAX_SIZE})" >&2
      : > "$logfile"
    fi
  fi
}

# Ensure a log file exists with restrictive permissions.  Creates the
# file if absent, then chmod 600 to prevent world-readable credential
# leaks from server output.
_oc-touch-log() {
  local logfile="$1"
  : >> "$logfile"
  chmod 600 "$logfile"
}

# Return a tmux command string for running a long-lived component with
# error handling: source env file, run the command, optionally pipe to
# tee, and on failure keep the pane visible for _OC_TMUX_ERROR_SLEEP
# seconds.
# $1: env file path (sourced in pane)
# $2: component label for error message
# $3: log file path (optional; if empty, skip tee)
# shift 3: the command and its arguments
_oc-tmux-run-cmd() {
  local env_file="$1" label="$2" logfile="$3"
  shift 3
  local dollar='$'
  if [[ -n "$logfile" ]]; then
    printf "source '%s' && { %s 2>&1 | tee -a '%s'; }; _oc_ec=%s{pipestatus[1]}; if (( _oc_ec != 0 )); then echo '%s exited with error (exit '%s{_oc_ec}')' | tee -a '%s'; sleep %s; fi" \
      "$env_file" "$*" "$logfile" "$dollar" "$label" "$dollar" "$logfile" "$_OC_TMUX_ERROR_SLEEP"
  else
    printf "source '%s' && %s || { echo '%s exited with error' >&2; sleep %s; }" \
      "$env_file" "$*" "$label" "$_OC_TMUX_ERROR_SLEEP"
  fi
}

# Return the tmux command string for attaching to opencode in the
# current project directory.  Escapes $PWD and $@ safely for shell
# injection.  Avoids duplicating --dir if the user already passed one.
_oc-attach-cmd() {
  local dir_flag have_dir extra
  dir_flag="--dir $(printf '%q' "$PWD")"
  have_dir=0
  extra=""
  if (( $# > 0 )); then
    for arg in "$@"; do
      if [[ "$arg" == "--dir" || "$arg" == "--dir="* ]]; then
        have_dir=1
      fi
    done
    extra=$(printf '%q ' "$@")
    extra="${extra% }"
  fi
  if (( have_dir )); then
    _oc-tmux-run-cmd "$_OC_SERVE_ENV_FILE" "opencode attach" "" opencode attach "http://localhost:${_OC_CADDY_PORT}" "${extra}"
  else
    _oc-tmux-run-cmd "$_OC_SERVE_ENV_FILE" "opencode attach" "" opencode attach "http://localhost:${_OC_CADDY_PORT}" "${dir_flag}" "${extra}"
  fi
}

# ── Netrc helper ────────────────────────────────────────────────────

# Create a temporary netrc file for curl --netrc-file.  Prints the
# netrc file path to stdout.  Caller MUST call _oc-netrc-cleanup when
# done.  INT/TERM traps are intentionally omitted — netrc must survive
# Ctrl-C during multi-session continuation loops so remaining curl calls
# still authenticate.  Callers clean up explicitly.
_oc-netrc-setup() {
  _oc-ensure-creds || return 1
  _OC_NETRC_TMPDIR="$(mktemp -d 2>/dev/null)" || { echo "Failed to create temp dir for netrc" >&2; return 1; }
  chmod 700 "$_OC_NETRC_TMPDIR"
  _OC_NETRC_FILE="$_OC_NETRC_TMPDIR/netrc"
  printf 'machine localhost login %s password %s\n' "$_OC_USER" "$_OC_PASS" > "$_OC_NETRC_FILE"
  chmod 600 "$_OC_NETRC_FILE"
}

_oc-netrc-cleanup() {
  rm -rf "${_OC_NETRC_TMPDIR:-}" 2>/dev/null
  unset _OC_NETRC_TMPDIR _OC_NETRC_FILE
}

# ── Health checks ───────────────────────────────────────────────────

_oc-health-check() {
  command curl -s -o /dev/null -w '%{http_code}' "http://localhost:${_OC_SERVE_PORT}/global/health" 2>/dev/null || echo "000"
}

_oc-server-up() {
  local code="$1"
  [[ "$code" == "200" || "$code" == "401" ]]
}

_oc-caddy-up() {
  local health_code
  health_code=$(command curl -s -o /dev/null -w '%{http_code}' "http://localhost:${_OC_CADDY_PORT}/global/health" 2>/dev/null)
  [[ "$health_code" == "200" || "$health_code" == "401" ]]
}

# Wait for caddy to actually proxy to the backend successfully.
# Returns 0 when a real API call (through caddy) gets a valid response.
_oc-caddy-ready() {
  local _cr_user="$_OC_USER" _cr_pass="$_OC_PASS"
  local _cr_code
  _cr_code=$(command curl -sS \
    -u "${_cr_user}:${_cr_pass}" \
    --connect-timeout 2 --max-time 5 \
    -o /dev/null -w '%{http_code}' \
    "http://localhost:${_OC_CADDY_PORT}/global/health" 2>/dev/null) || _cr_code="000"
  [[ "$_cr_code" == "200" || "$_cr_code" == "401" ]]
}

# Kill any stale server or caddy processes bound to our ports.  When
# tmux sessions are killed, child processes can outlive the session.
# Called before boot so SO_REUSEPORT doesn't send traffic to zombie
# caddy instances with stale proxy config.

_oc-debug-snapshot() {
  echo "--- debug snapshot $(date +%H:%M:%S) ---" >&2
  echo "listeners on $_OC_SERVE_PORT / $_OC_CADDY_PORT:" >&2
  lsof -iTCP:"$_OC_SERVE_PORT" -iTCP:"$_OC_CADDY_PORT" -sTCP:LISTEN -P 2>/dev/null | sed 's/^/  /' >&2 || echo "  (none)" >&2
  echo "established connections on $_OC_SERVE_PORT / $_OC_CADDY_PORT:" >&2
  lsof -iTCP:"$_OC_SERVE_PORT" -iTCP:"$_OC_CADDY_PORT" -P 2>/dev/null | grep -v LISTEN | sed 's/^/  /' >&2 || echo "  (none)" >&2
  echo "openode processes:" >&2
  ps aux | grep -i '[o]pencode' | sed 's/^/  /' >&2 || echo "  (none)" >&2
  echo "caddy processes:" >&2
  ps aux | grep -i '[c]addy' | sed 's/^/  /' >&2 || echo "  (none)" >&2
  echo "direct curl test:" >&2
  echo "  http://localhost:$_OC_CADDY_PORT/global/health: $(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 2 http://localhost:$_OC_CADDY_PORT/global/health 2>&1 || echo 'FAIL')" >&2
  echo "  http://localhost:$_OC_SERVE_PORT/global/health: $(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 2 http://localhost:$_OC_SERVE_PORT/global/health 2>&1 || echo 'FAIL')" >&2
  echo "tmux sessions:" >&2
  tmux list-sessions 2>/dev/null | sed 's/^/  /' >&2 || echo "  (no tmux server)" >&2
  echo "--- end snapshot ---" >&2
}

_oc-kill-stale-processes() {
  local pid port
  echo "[$(date +%H:%M:%S)] scanning for stale processes on ports $_OC_SERVE_PORT/$_OC_CADDY_PORT" >&2
  for port in "$_OC_SERVE_PORT" "$_OC_CADDY_PORT"; do
    local pids
    pids=$(lsof -ti TCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
      while read -r pid; do
        [[ -z "$pid" ]] && continue
        local cmd
        cmd=$(ps -o comm= -p "$pid" 2>/dev/null || echo "unknown")
        echo "[$(date +%H:%M:%S)] killed stale $cmd (pid $pid) on port $port" >&2
        kill "$pid" 2>/dev/null || true
      done <<< "$pids"
    fi
  done
  local _oc_kill_wait=0
  while (( _oc_kill_wait < 5 )); do
    local found=0
    for port in "$_OC_SERVE_PORT" "$_OC_CADDY_PORT"; do
      lsof -ti TCP:"$port" -sTCP:LISTEN 2>/dev/null | read -r pid 2>/dev/null && found=1
    done
    (( found == 0 )) && break
    _oc_kill_wait=$(( _oc_kill_wait + 1 ))
    sleep 1
  done
  echo "[$(date +%H:%M:%S)] port scan complete" >&2
  echo "[$(date +%H:%M:%S)] current listeners:" >&2
  lsof -iTCP:"$_OC_SERVE_PORT" -iTCP:"$_OC_CADDY_PORT" -sTCP:LISTEN -P 2>/dev/null | sed 's/^/  /' >&2 || echo "  (none)" >&2
}

_oc-kill-stale-watchdog() {
  local pidfile="${_OC_CACHE_DIR}/server.watchdog-pid"
  if [[ -f "$pidfile" ]]; then
    local old_pid
    old_pid=$(<"$pidfile")
    rm -f "$pidfile"
    if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
      echo "[$(date +%H:%M:%S)] killed stale watchdog (pid $old_pid)" >&2
      kill "$old_pid" 2>/dev/null || true
    fi
  fi
}

_oc-watchdog-alive() {
  local pidfile="${_OC_CACHE_DIR}/server.watchdog-pid"
  [[ -f "$pidfile" ]] || return 1
  local pid
  pid=$(<"$pidfile")
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

# ── Caddy helpers ───────────────────────────────────────────────────

# Compute the bcrypt hash for the Caddy basic_auth directive using
# htpasswd.  Reads the password from stdin (-i flag) to avoid leaking
# credentials in the process list via argv.  Extracts the hash portion
# (everything after the first colon) and validates the bcrypt format
# ($2a$, $2b$, or $2y$).  Caches the result to _OC_CADDY_HASH_FILE.
_oc-caddy-hash() {
  local hash
  if ! command -v htpasswd &>/dev/null; then
    echo "Install apache2-utils: brew install httpd" >&2
    return 1
  fi
  hash=$(printf '%s' "$_OC_PASS" | command htpasswd -niBC "$_OC_BCRYPT_COST" "$_OC_USER" 2>/dev/null | sed 's/^[^:]*://')
  if [[ ! "$hash" =~ ^[$]2[aby][$] ]]; then
    echo "Failed to compute valid bcrypt hash.  Check htpasswd installation." >&2
    return 1
  fi
  if [[ -n "$hash" ]]; then
    printf '%s' "$hash" > "$_OC_CADDY_HASH_FILE"
    chmod 600 "$_OC_CADDY_HASH_FILE"
  fi
  echo "$hash"
}

_oc-caddy-write-env() {
  local auth_b64 caddy_hash
  auth_b64=$(printf '%s:%s' "$_OC_USER" "$_OC_PASS" | base64)
  caddy_hash=$(_oc-caddy-hash) || return 1
  cat > "$_OC_CADDY_ENV_FILE" <<EOF
export OC_CADDY_PORT=${_OC_CADDY_PORT}
export OC_SERVE_PORT=${_OC_SERVE_PORT}
export OC_AUTH_B64=${auth_b64}
export OC_CADDY_USER=${_OC_USER}
export OC_CADDY_HASH='${caddy_hash}'
EOF
  chmod 600 "$_OC_CADDY_ENV_FILE"
}

_oc-serve-write-env() {
  cat > "$_OC_SERVE_ENV_FILE" <<EOF
export OPENCODE_SERVER_USERNAME=$(printf '%q' "$_OC_USER")
export OPENCODE_SERVER_PASSWORD=$(printf '%q' "$_OC_PASS")
export OPENCODE_AUTO_HEAP_SNAPSHOT=1
EOF
  chmod 600 "$_OC_SERVE_ENV_FILE" || return 1
}

# ── Lock directory helpers ──────────────────────────────────────────

_oc-lockdir-write-pid() {
  local lockdir="$1"
  echo $$ > "$lockdir/pid"
}

_oc-lockdir-stale() {
  local lockdir="$1"
  local now
  now=$(date +%s)
  local lock_mtime
  lock_mtime=$(_oc-stat-mtime "$lockdir" || echo 0)
  local lock_age=$(( now - lock_mtime ))
  if [[ -f "$lockdir/pid" ]]; then
    local pid
    pid=$(<"$lockdir/pid")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      return 1
    fi
    return 0
  fi
  (( lock_age > _OC_STALE_LOCK_THRESHOLD ))
}

# ── Server lifecycle ────────────────────────────────────────────────

# Start the opencode server and caddy reverse proxy WITHOUT acquiring
# the lockdir.  Used internally by _oc-ensure-server (which handles
# locking).  This avoids recursive lock acquisition deadlocks.
_oc-boot-server() {
  echo "[$(date +%H:%M:%S)] booting server" >&2
  _oc-ensure-creds || return 1
  _oc-kill-stale-processes
  _oc-kill-stale-watchdog
  _oc-ensure-logs

  _oc-rotate-log "$_OC_LOGDIR/serve.log"
  _oc-rotate-log "$_OC_LOGDIR/caddy.log"
  _oc-touch-log "$_OC_LOGDIR/serve.log"
  _oc-touch-log "$_OC_LOGDIR/caddy.log"

  echo "# Session started $(date +%Y-%m-%dT%H:%M:%S%z)" >> "$_OC_LOGDIR/serve.log"
  echo "# Session started $(date +%Y-%m-%dT%H:%M:%S%z)" >> "$_OC_LOGDIR/caddy.log"

  _oc-serve-write-env || return 1
  _oc-caddy-write-env || return 1

  command tmux new-session -d -s "$_OC_SERVER_SESSION" -c "$HOME" \
    "$(_oc-tmux-run-cmd "$_OC_SERVE_ENV_FILE" "opencode serve" "$_OC_LOGDIR/serve.log" opencode serve --port "$_OC_SERVE_PORT" --hostname 127.0.0.1 --print-logs --log-level INFO)"

  command tmux split-window -t "$_OC_SERVER_SESSION" -c "$HOME" \
    "$(_oc-tmux-run-cmd "$_OC_CADDY_ENV_FILE" "caddy" "$_OC_LOGDIR/caddy.log" caddy run --config "${_OC_CADDYDIR}/Caddyfile")"

  command tmux select-layout -t "$_OC_SERVER_SESSION" even-vertical

  echo "[$(date +%H:%M:%S)] waiting for opencode serve (port $_OC_SERVE_PORT)..." >&2
  local i=0 serve_health
  while (( i < _OC_SERVE_START_TIMEOUT )); do
    i=$(( i + 1 ))
    sleep 1
    serve_health=$(_oc-health-check)
    if _oc-server-up "$serve_health"; then
      echo "[$(date +%H:%M:%S)] serve health check passed (HTTP $serve_health)" >&2
      local j=0
      while (( j < _OC_CADDY_START_TIMEOUT )); do
        j=$(( j + 1 ))
        sleep 1
        if _oc-caddy-up; then
          echo "[$(date +%H:%M:%S)] caddy health check passed (port $_OC_CADDY_PORT)" >&2
          echo "# Watchdog started $(date +%Y-%m-%dT%H:%M:%S%z)" >> "$_OC_LOGDIR/serve.log"
          rm -f "${_OC_CACHE_DIR}/server.graceful-stop" 2>/dev/null
          (_oc-server-watchdog "$_OC_SERVE_PORT" &>/dev/null </dev/null &)
          return 0
        fi
      done
      echo "[$(date +%H:%M:%S)] opencode server up but caddy not responding after ${_OC_CADDY_START_TIMEOUT}s.  Check ${_OC_LOGDIR}/caddy.log" >&2
      return 1
    fi
  done

  echo "[$(date +%H:%M:%S)] opencode server not responding after ${_OC_SERVE_START_TIMEOUT}s" >&2
  echo "Check: tmux attach -t $_OC_SERVER_SESSION  or  ${_OC_LOGDIR}/serve.log" >&2
  return 1
}

_oc-ensure-server() {
  local lockdir="$_OC_CACHE_DIR/server.lock"
  mkdir -p "$_OC_CACHE_DIR"

  if [[ -d "$lockdir" ]] && _oc-lockdir-stale "$lockdir"; then
    rmdir "$lockdir" 2>/dev/null && echo "warning: removed stale server lock (likely after crash or SIGKILL)" >&2
  fi

  local _oc_lock_retries=0
  until mkdir "$lockdir" 2>/dev/null; do
    _oc_lock_retries=$(( _oc_lock_retries + 1 ))
    if (( _oc_lock_retries > _OC_LOCK_MAX_RETRIES )); then
      echo "Timed out waiting for server lock after $(( _OC_LOCK_MAX_RETRIES * _OC_LOCK_RETRY_MS ))s. Another process may hold the lock." >&2
      return 1
    fi
    if (( _oc_lock_retries % 20 == 0 )); then
      echo "Waiting for server lock... (${_oc_lock_retries} retries)" >&2
    fi
    sleep "$_OC_LOCK_RETRY_MS"
  done
  _oc-lockdir-write-pid "$lockdir"
  trap 'rm -rf "$lockdir" 2>/dev/null' INT TERM

  if ! _oc-ensure-creds; then
    rm -rf "$lockdir" 2>/dev/null; trap - INT TERM 2>/dev/null
    return 1
  fi

  local serve_health
  serve_health=$(_oc-health-check)
  if _oc-server-up "$serve_health"; then
    _OC_SERVER_BOOTED=0
    _oc-serve-write-env
    if ! _oc-watchdog-alive; then
      echo "# Watchdog restarted $(date +%Y-%m-%dT%H:%M:%S%z)" >> "$_OC_LOGDIR/serve.log"
      rm -f "${_OC_CACHE_DIR}/server.graceful-stop" 2>/dev/null
      (_oc-server-watchdog "$_OC_SERVE_PORT" &>/dev/null </dev/null &)
    fi
    if ! _oc-caddy-up; then
      _oc-caddy-restart
      local rc=$?
      rm -rf "$lockdir" 2>/dev/null; trap - INT TERM 2>/dev/null
      return $rc
    fi
    rm -rf "$lockdir" 2>/dev/null; trap - INT TERM 2>/dev/null
    return 0
  fi

  if ! command -v tmux &>/dev/null; then
    echo "Install tmux: brew install tmux" >&2
    rm -rf "$lockdir" 2>/dev/null; trap - INT TERM 2>/dev/null
    return 1
  fi

  if ! command -v caddy &>/dev/null; then
    echo "Install caddy: brew install caddy" >&2
    rm -rf "$lockdir" 2>/dev/null; trap - INT TERM 2>/dev/null
    return 1
  fi

  if command tmux has-session -t "$_OC_SERVER_SESSION" 2>/dev/null; then
    command tmux kill-session -t "$_OC_SERVER_SESSION"
  fi

  _OC_SERVER_BOOTED=1
  _oc-boot-server
  local rc=$?
  rm -rf "$lockdir" 2>/dev/null; trap - INT TERM 2>/dev/null
  return $rc
}

# ── Server watchdog ──────────────────────────────────────────────────
#
# Background monitor that runs after _oc-boot-server succeeds.  Checks
# every 30s that the server process is alive and logs its RSS.  On
# unexpected exit (no graceful-stop marker) writes a crash report to
# serve.log and a dedicated crash file.
# Variables:
#   _OC_WATCHDOG_CHECK_INTERVAL=30     seconds between checks
#   _OC_WATCHDOG_LOG_DIR               where crash reports are written
#   _OC_WATCHDOG_CRASH_MB=20000        RSS threshold for OOM-style kill
_OC_WATCHDOG_CHECK_INTERVAL="${_OC_WATCHDOG_CHECK_INTERVAL:-30}"
_OC_WATCHDOG_LOG_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/opencode/memwatch"
_OC_WATCHDOG_CRASH_MB="${_OC_WATCHDOG_CRASH_MB:-20000}"

_oc-server-watchdog() {
  set +x +v +o xtrace +o verbose 2>/dev/null
  local serve_port="$1"
  local graceful_file="${_OC_CACHE_DIR}/server.graceful-stop"
  local logfile="${_OC_LOGDIR}/serve.log"
  local pidfile="${_OC_CACHE_DIR}/server.watchdog-pid"
  mkdir -p "$_OC_WATCHDOG_LOG_DIR"

  # Register PID so _oc-boot-server can kill stale watchdogs
  echo $$ > "$pidfile"
  chmod 600 "$pidfile"

  local fd_info
  fd_info=$(lsof -p $$ -a -d 1,2 2>/dev/null || echo "(lsof failed)")
  echo "watchdog FDs: $fd_info" >> "$logfile"

  while true; do
    sleep "$_OC_WATCHDOG_CHECK_INTERVAL"

    # Find server PID via the listen port
    local pids
    pids=$(lsof -ti TCP:"$serve_port" -sTCP:LISTEN 2>/dev/null || true)
    if [[ -z "$pids" ]]; then
      # Server is gone
      if [[ -f "$graceful_file" ]]; then
        rm -f "$graceful_file"
        exit 0
      fi
      local now
      now=$(date '+%Y-%m-%dT%H:%M:%S%z')
      local crash_file="$_OC_WATCHDOG_LOG_DIR/crash-$(date +%s).txt"
      {
        echo "=== watchdog crash at $now ==="
        echo "Server process on port $serve_port disappeared unexpectedly."
        echo "Last 10 lines of serve.log:"
        tail -10 "$logfile" 2>/dev/null
        echo ""
        echo "--- tmux session status ---"
        tmux has-session -t "$_OC_SERVER_SESSION" 2>/dev/null && \
          tmux capture-pane -t "$_OC_SERVER_SESSION" -p -S -20 2>/dev/null || echo "(tmux session gone)"
        echo ""
        echo "--- listeners ---"
        lsof -iTCP:"$_OC_SERVE_PORT","$_OC_CADDY_PORT" -sTCP:LISTEN -P 2>/dev/null || echo "(none)"
        echo ""
        echo "--- vm_stat ---"
        vm_stat 2>/dev/null | head -10
      } > "$crash_file"
      chmod 600 "$crash_file"
      echo "$now watchdog: server port $serve_port died unexpectedly — crash report at $crash_file" >> "$logfile"
      exit 1
    fi

    local rss_kb now
    rss_kb=$(ps -o rss= -p "${pids%%$'\n'*}" 2>/dev/null | tr -d ' ') || rss_kb=0
    now=$(date '+%Y-%m-%dT%H:%M:%S%z')
    if (( rss_kb > _OC_WATCHDOG_CRASH_MB * 1024 )); then
      local oom_file="$_OC_WATCHDOG_LOG_DIR/oom-$(date +%s).txt"
      {
        echo "=== watchdog OOM kill at $now ==="
        echo "PID ${pids%%$'\n'*} RSS $(( rss_kb / 1024 )) MB exceeded ${_OC_WATCHDOG_CRASH_MB} MB"
        echo "--- ps ---"
        ps aux | grep '[o]pencode' 2>/dev/null
        echo "--- vm_stat ---"
        vm_stat 2>/dev/null | head -10
      } > "$oom_file"
      chmod 600 "$oom_file"
      echo "$now watchdog: server RSS $(( rss_kb / 1024 )) MB exceeded ${_OC_WATCHDOG_CRASH_MB} MB — report at $oom_file" >> "$logfile"
      kill "${pids%%$'\n'*}" 2>/dev/null || true
      exit 1
    fi

    # Periodic RSS log (INFO only)
    if (( rss_kb > 0 )); then
      printf '%s watchdog: server RSS %d MB\n' "$now" "$(( rss_kb / 1024 ))" >> "$logfile"
    fi
  done
}

_oc-caddy-restart() {
  if ! command -v caddy &>/dev/null; then
    echo "Install caddy: brew install caddy" >&2
    return 1
  fi

  if ! command tmux has-session -t "$_OC_SERVER_SESSION" 2>/dev/null; then
    _oc-boot-server
    return $?
  fi

  _oc-ensure-creds || return 1
  _oc-ensure-logs
  _oc-caddy-write-env || return 1

  local pane_count caddy_pane_id
  pane_count=$(command tmux list-panes -t "$_OC_SERVER_SESSION" -F '#{pane_id}' 2>/dev/null | wc -l | tr -d ' ')
  if (( pane_count < 2 )); then
    command tmux split-window -t "$_OC_SERVER_SESSION" -c "$HOME" \
      "$(_oc-tmux-run-cmd "$_OC_CADDY_ENV_FILE" "caddy" "$_OC_LOGDIR/caddy.log" caddy run --config "${_OC_CADDYDIR}/Caddyfile")"
  else
    caddy_pane_id=$(command tmux list-panes -t "$_OC_SERVER_SESSION" -F '#{pane_id} #{pane_current_command}' 2>/dev/null | grep caddy | awk '{print $1}')
    if [[ -z "$caddy_pane_id" ]]; then
      command tmux split-window -t "$_OC_SERVER_SESSION" -c "$HOME" \
        "$(_oc-tmux-run-cmd "$_OC_CADDY_ENV_FILE" "caddy" "$_OC_LOGDIR/caddy.log" caddy run --config "${_OC_CADDYDIR}/Caddyfile")"
      command tmux select-layout -t "$_OC_SERVER_SESSION" even-vertical
      return 0
    fi
    _oc-rotate-log "$_OC_LOGDIR/caddy.log"
    command tmux send-keys -t "$caddy_pane_id" C-c
    local _oc_caddy_wait=0
    while (( _oc_caddy_wait < 5 )); do
      if command tmux list-panes -t "$_OC_SERVER_SESSION" -F '#{pane_id} #{pane_dead}' 2>/dev/null | grep -q "^${caddy_pane_id} 1"; then
        break
      fi
      _oc_caddy_wait=$(( _oc_caddy_wait + 1 ))
      sleep 1
    done
    command tmux send-keys -t "$caddy_pane_id" \
      "$(_oc-tmux-run-cmd "$_OC_CADDY_ENV_FILE" "caddy" "$_OC_LOGDIR/caddy.log" caddy run --config "${_OC_CADDYDIR}/Caddyfile")" Enter
  fi
  command tmux select-layout -t "$_OC_SERVER_SESSION" even-vertical

  local i=0
  while (( i < _OC_CADDY_START_TIMEOUT )); do
    i=$(( i + 1 ))
    sleep 1
    if _oc-caddy-up; then
      return 0
    fi
  done
  echo "caddy not responding after restart (${_OC_CADDY_START_TIMEOUT}s).  Check ${_OC_LOGDIR}/caddy.log" >&2
  return 1
}

# ── Session repair ──────────────────────────────────────────────────

# Phase 1: repair the SQLite database.  Marks orphaned assistant
# messages as completed and running/pending tool parts as errored.
# Can run without a server.  opencode stores timestamps in MILLISECONDS
# in all time_created / time_updated columns.
_oc-repair-sessions-db() {
  local db="${XDG_DATA_HOME:-$HOME/.local/share}/opencode/opencode.db"
  if [[ ! -f "$db" ]]; then return 0; fi

  local failed_flag="$_OC_CACHE_DIR/.repair_failed.$$"
  rm -f "$failed_flag"

  command sqlite3 -noheader "$db" "
    WITH latest_msg AS (
      SELECT session_id, MAX(time_created) AS max_created
      FROM message
      GROUP BY session_id
    ),
    orphaned AS (
      SELECT m.id AS msg_id, m.session_id
      FROM message m
      JOIN latest_msg lm ON m.session_id = lm.session_id AND m.time_created = lm.max_created
      WHERE json_extract(m.data, '\$.role') = 'assistant'
        AND json_extract(m.data, '\$.time.completed') IS NULL
    )
    SELECT o.msg_id, o.session_id, s.title, s.time_updated
    FROM orphaned o
    JOIN session s ON s.id = o.session_id
  " 2>/dev/null | while IFS='|' read -r msg_id sess_id session_title time_updated; do
    [[ -z "$sess_id" ]] && continue

    if ! _oc-valid-id "$msg_id" || ! _oc-valid-id "$sess_id"; then
      echo "  warning: skipping invalid ID in repair: msg=$msg_id sess=$sess_id" >&2
      continue
    fi

    local now
    now=$(date +%s000)

    if ! command sqlite3 "$db" "
      UPDATE message
      SET data = json_set(data, '\$.time.completed', $now),
          time_updated = $now
      WHERE id = '$msg_id'
    " 2>/dev/null; then
      echo "  warning: failed to update message $msg_id" >&2
      : > "$failed_flag"
    fi

    if ! command sqlite3 "$db" "
      UPDATE part
      SET data = json_set(data, '\$.state.status', 'error',
               json_set(data, '\$.state.error', 'Tool execution was interrupted (server restart)')),
          time_updated = $now
      WHERE session_id = '$sess_id'
        AND json_extract(data, '\$.state.status') IN ('running', 'pending')
    " 2>/dev/null; then
      echo "  warning: failed to update parts for session $sess_id" >&2
      : > "$failed_flag"
    fi

    echo "  repaired database for session $sess_id ($session_title)" >&2
    echo "$now|$sess_id|$time_updated"
  done

  if [[ -f "$failed_flag" ]]; then
    rm -f "$failed_flag"
    return 1
  fi
}

# Phase 2: submit API continuation prompts for sessions that were
# actively running when the server crashed.  Must be called AFTER
# _oc-ensure-server succeeds.  Expects pipe-delimited input on stdin:
# repair_now|sess_id|original_time_updated.
# _OC_SUBMIT_RETRIES=3               max retries per session for HTTP 000
# _OC_SUBMIT_RETRY_DELAY=2           seconds between retry attempts
# _OC_SUBMIT_CADDY_WARMUP=3          seconds to wait after caddy health
#                                    check before submitting API calls

_OC_SUBMIT_RETRIES="${_OC_SUBMIT_RETRIES:-3}"
_OC_SUBMIT_RETRY_DELAY="${_OC_SUBMIT_RETRY_DELAY:-2}"
_OC_SUBMIT_CADDY_WARMUP="${_OC_SUBMIT_CADDY_WARMUP:-3}"

_oc-repair-sessions-continue() {
  echo "[$(date +%H:%M:%S)] starting continuation prompts" >&2
  mkdir -p "$_OC_CACHE_DIR"
  _oc-ensure-creds || return 1

  local api_url="http://localhost:${_OC_CADDY_PORT}"

  local saved_data
  saved_data=$(cat)

  if [[ -z "$saved_data" ]]; then
    echo "[$(date +%H:%M:%S)] no sessions to submit, done" >&2
    return 0
  fi

  echo "[$(date +%H:%M:%S)] waiting for caddy on port $_OC_CADDY_PORT..." >&2
  local _oc_ready_wait=0
  while (( _oc_ready_wait < 10 )); do
    if _oc-caddy-up; then
      echo "[$(date +%H:%M:%S)] caddy health check passed" >&2
      break
    fi
    _oc_ready_wait=$(( _oc_ready_wait + 1 ))
    sleep 1
  done
  if ! _oc-caddy-up; then
    echo "[$(date +%H:%M:%S)] warning: caddy not responding, skipping continuation prompts" >&2
    return 1
  fi

  echo "[$(date +%H:%M:%S)] warming up (${_OC_SUBMIT_CADDY_WARMUP}s)..." >&2
  sleep "$_OC_SUBMIT_CADDY_WARMUP"

  echo "[$(date +%H:%M:%S)] verifying caddy proxy is ready..." >&2
  local _proxy_ready_wait=0
  while (( _proxy_ready_wait < 15 )); do
    if _oc-caddy-ready; then
      echo "[$(date +%H:%M:%S)] caddy proxy ready" >&2
      break
    fi
    _proxy_ready_wait=$(( _proxy_ready_wait + 1 ))
    sleep 1
  done
  if ! _oc-caddy-ready; then
    echo "[$(date +%H:%M:%S)] warning: caddy proxy not ready after 15s, continuing anyway" >&2
  fi

  local _cont_log="$_OC_LOGDIR/continuation.log"
  _oc-ensure-logs
  _oc-rotate-log "$_cont_log"
  _oc-touch-log "$_cont_log"
  echo "# Restart $(date +%Y-%m-%dT%H:%M:%S%z)" >> "$_cont_log"

  echo "$saved_data" | while IFS='|' read -r repair_now sess_id time_updated; do
    [[ -z "$sess_id" ]] && continue

    if [[ -z "$time_updated" || ! "$time_updated" =~ ^[0-9]+$ ]]; then
      echo "[$(date +%H:%M:%S)] skipped session $sess_id (missing or invalid time_updated)" >&2
      continue
    fi

    local session_age_ms=$(( repair_now - time_updated ))

    if (( session_age_ms >= _OC_RESTART_THRESHOLD_MS )); then
      echo "[$(date +%H:%M:%S)] skipped continuation prompt (session crashed before this restart)" >&2
      continue
    fi

    if ! _oc-valid-id "$sess_id"; then
      echo "[$(date +%H:%M:%S)] warning: skipping invalid session ID in continuation: $sess_id" >&2
      continue
    fi

    local prompt_text="The server was just restarted but your session context is intact. Please continue your work from where you left off."
    local payload
    payload=$(command jq -n \
      --arg text "$prompt_text" \
      '{parts: [{type: "text", text: $text}]}' 2>/dev/null)

    if [[ -z "$payload" ]]; then
      echo "[$(date +%H:%M:%S)] warning: jq not available, skipping API submit for $sess_id" >&2
      continue
    fi

    local _submit_user="$_OC_USER" _submit_pass="$_OC_PASS"
    local check_code
    check_code=$(command curl -sS \
      -u "${_submit_user}:${_submit_pass}" \
      --connect-timeout 5 --max-time 5 \
      -o /dev/null -w '%{http_code}' \
      "${api_url}/session/${sess_id}" 2>/dev/null) || check_code="000"

    if [[ "$check_code" != "200" ]]; then
      echo "[$(date +%H:%M:%S)] warning: session $sess_id not reachable (HTTP $check_code), skipping" >&2
      echo "[$(date +%H:%M:%S)] skipped $sess_id (pre-check HTTP $check_code)" >> "$_cont_log"
      continue
    fi

    echo "[$(date +%H:%M:%S)] submitting continuation to $sess_id" >&2
    echo "[$(date +%H:%M:%S)] DEBUG: api_url=$api_url" >&2
    local http_code curl_err attempt
    local _tmp_err="$_OC_CACHE_DIR/curl-err.txt"
    http_code="000"
    for (( attempt=1; attempt <= _OC_SUBMIT_RETRIES; attempt++ )); do
      echo "[$(date +%H:%M:%S)] DEBUG: attempt $attempt for $sess_id" >&2
      http_code=$(command curl -s -o /dev/null -w '%{http_code}' \
        -u "${_submit_user}:${_submit_pass}" \
        --connect-timeout 5 \
        --max-time 10 \
        -H 'Content-Type: application/json' \
        -d "$payload" \
        "${api_url}/session/${sess_id}/message" 2> "$_tmp_err") || true

      echo "[$(date +%H:%M:%S)] DEBUG: http_code=$http_code for $sess_id" >&2
      if [[ "$http_code" == "200" ]]; then
        echo "[$(date +%H:%M:%S)] submitted continuation prompt to $sess_id" >&2
        break
      fi

      if [[ "$http_code" == "000" ]]; then
        curl_err=$(cat "$_tmp_err" 2>/dev/null | head -1)
        echo "[$(date +%H:%M:%S)] DEBUG: curl_err='$curl_err' for $sess_id" >&2

        # Empty stderr = TCP connection succeeded but the server didn't
        # send HTTP headers before --max-time.  This is normal when the
        # AI is still thinking — the 200 header only arrives with the
        # first SSE event.  The POST was already accepted, so don't
        # retry; retrying would submit duplicate messages.
        if [[ -z "$curl_err" ]]; then
          echo "[$(date +%H:%M:%S)] submitted continuation to $sess_id (server accepted, timed out waiting for SSE headers — message delivered)" >&2
          break
        fi

        if (( attempt < _OC_SUBMIT_RETRIES )); then
          echo "[$(date +%H:%M:%S)] retrying $sess_id (HTTP 000, curl: ${curl_err:-connection refused})" >&2
          if ! _oc-caddy-up; then
            echo "[$(date +%H:%M:%S)] caddy appears down, restarting before retry $attempt for $sess_id" >&2
            _oc-caddy-restart || true
            sleep "$_OC_SUBMIT_CADDY_WARMUP"
          else
            echo "[$(date +%H:%M:%S)] caddy is up but connection refused — checking listeners..." >&2
            lsof -iTCP:"$_OC_SERVE_PORT","$_OC_CADDY_PORT" -sTCP:LISTEN -P 2>/dev/null | sed 's/^/  /' >&2 || echo "  (no listeners)" >&2
          fi
          sleep "$_OC_SUBMIT_RETRY_DELAY"
        else
          echo "[$(date +%H:%M:%S)] FAILED: $sess_id after $_OC_SUBMIT_RETRIES attempts (HTTP ${http_code}, curl: ${curl_err:-connection refused})" >&2
          echo "[$(date +%H:%M:%S)]   full curl stderr:" >&2
          cat "$_tmp_err" 2>/dev/null | sed 's/^/    /' >&2
          _oc-debug-snapshot
        fi
      else
        echo "[$(date +%H:%M:%S)] FAILED: $sess_id (HTTP $http_code)" >&2
        break
      fi
    done
    rm -f "$_tmp_err" 2>/dev/null
    echo "[$(date +%H:%M:%S)] $sess_id: HTTP $http_code" >> "$_cont_log"
  done

  echo "[$(date +%H:%M:%S)] continuation prompts finished" >&2
}

# ── Public commands ─────────────────────────────────────────────────

oc-web() {
  echo "[$(date +%H:%M:%S)] oc-web start" >&2
  _OC_SERVER_BOOTED=""
  _oc-ensure-server || return 1
  if [[ "${_OC_SERVER_BOOTED:-0}" == "1" ]]; then
    local _oc_repair_data
    _oc_repair_data=$(_oc-repair-sessions-db) || echo "[$(date +%H:%M:%S)] warning: some sessions could not be repaired" >&2
    if [[ -n "$_oc_repair_data" ]]; then
      echo "$_oc_repair_data" | _oc-repair-sessions-continue || echo "[$(date +%H:%M:%S)] warning: some continuation prompts failed" >&2
    fi
  fi
  command $_OC_OPEN "http://localhost:${_OC_CADDY_PORT}"
  echo "[$(date +%H:%M:%S)] opencode web UI at http://localhost:${_OC_CADDY_PORT}" >&2
}

oc-stop() {
  echo "[$(date +%H:%M:%S)] oc-stop start" >&2
  echo "# oc-stop $(date +%Y-%m-%dT%H:%M:%S%z)" >> "$_OC_LOGDIR/serve.log"
  : > "${_OC_CACHE_DIR}/server.graceful-stop" 2>/dev/null
  if command tmux has-session -t "$_OC_SERVER_SESSION" 2>/dev/null; then
    command tmux kill-session -t "$_OC_SERVER_SESSION"
    echo "[$(date +%H:%M:%S)] killed opencode server tmux session" >&2
    echo "# tmux session killed" >> "$_OC_LOGDIR/serve.log"
  else
    echo "[$(date +%H:%M:%S)] no tmux server session found" >&2
  fi
  _oc-kill-stale-processes
  echo "[$(date +%H:%M:%S)] server stopped" >&2
  echo "# oc-stop complete $(date +%Y-%m-%dT%H:%M:%S%z)" >> "$_OC_LOGDIR/serve.log"
}

oc-restart() {
  echo "[$(date +%H:%M:%S)] oc-restart start" >&2
  _OC_SERVER_BOOTED=""
  echo "# oc-restart $(date +%Y-%m-%dT%H:%M:%S%z)" >> "$_OC_LOGDIR/serve.log"
  oc-stop
  echo "[$(date +%H:%M:%S)] repairing interrupted sessions..." >&2
  local repair_data
  repair_data=$(_oc-repair-sessions-db) || echo "[$(date +%H:%M:%S)] warning: some sessions could not be repaired" >&2
  echo "[$(date +%H:%M:%S)] starting server..." >&2
  _oc-ensure-server || return 1
  if [[ -n "$repair_data" ]]; then
    echo "[$(date +%H:%M:%S)] submitting continuation prompts..." >&2
    echo "$repair_data" | _oc-repair-sessions-continue || echo "[$(date +%H:%M:%S)] warning: some continuation prompts failed" >&2
  fi
  echo "# oc-restart complete $(date +%Y-%m-%dT%H:%M:%S%z)" >> "$_OC_LOGDIR/serve.log"
  echo "[$(date +%H:%M:%S)] done." >&2
}

# shellcheck disable=SC2120
oc-tui() {
  _OC_SERVER_BOOTED=""
  _oc-ensure-server || return 1
  if [[ "${_OC_SERVER_BOOTED:-0}" == "1" ]]; then
    local _oc_repair_data
    _oc_repair_data=$(_oc-repair-sessions-db) || echo "warning: some sessions could not be repaired" >&2
    if [[ -n "$_oc_repair_data" ]]; then
      echo "$_oc_repair_data" | _oc-repair-sessions-continue || echo "warning: some continuation prompts failed" >&2
    fi
  fi

  _oc-ensure-creds || return 1

  local session_name window_name
  session_name=$(_oc-session-name)
  window_name=$(_oc-window-name)

  local attach_args=(opencode attach "http://localhost:${_OC_CADDY_PORT}" --dir "$PWD")
  if (( $# > 0 )); then
    local has_dir=0 arg
    for arg in "$@"; do
      if [[ "$arg" == "--dir" || "$arg" == "--dir="* ]]; then
        has_dir=1
      fi
    done
    if (( has_dir )); then
      attach_args=(opencode attach "http://localhost:${_OC_CADDY_PORT}")
    fi
    attach_args+=("$@")
  fi

  if command tmux has-session -t "$session_name" 2>/dev/null; then
    if command tmux list-windows -t "$session_name" -F '#{window_name}' 2>/dev/null | grep -qx "$window_name"; then
      if [[ -n "$TMUX" ]]; then
        local current_location
        current_location=$(command tmux display-message -p '#{session_name}:#{window_name}')
        if [[ "$current_location" == "$session_name:$window_name" ]]; then
          OPENCODE_SERVER_USERNAME="$_OC_USER" OPENCODE_SERVER_PASSWORD="$_OC_PASS" command "${attach_args[@]}"
          return $?
        fi
        command tmux split-window -t "$session_name:$window_name" -c "$PWD" \
          "$(_oc-attach-cmd "$@")"
        command tmux select-layout -t "$session_name:$window_name" even-vertical
        command tmux switch-client -t "$session_name"
        command tmux select-window -t "$session_name:$window_name"
      else
        command tmux split-window -t "$session_name:$window_name" -c "$PWD" \
          "$(_oc-attach-cmd "$@")"
        command tmux select-layout -t "$session_name:$window_name" even-vertical
        command tmux attach -t "$session_name"
        command tmux select-window -t "$session_name:$window_name"
      fi
    else
      command tmux new-window -t "$session_name" -n "$window_name" -c "$PWD" \
        "$(_oc-attach-cmd "$@")"
      if [[ -n "$TMUX" ]]; then
        command tmux switch-client -t "$session_name"
        command tmux select-window -t "$session_name:$window_name"
      else
        command tmux attach -t "$session_name"
        command tmux select-window -t "$session_name:$window_name"
      fi
    fi
    return 0
  fi

  if [[ -n "$TMUX" ]]; then
    command tmux new-session -d -s "$session_name" -n "$window_name" -c "$PWD" \
      "$(_oc-attach-cmd "$@")"
    command tmux switch-client -t "$session_name"
    command tmux select-window -t "$session_name:$window_name"
  else
    command tmux new-session -s "$session_name" -n "$window_name" -c "$PWD" \
      "$(_oc-attach-cmd "$@")"
  fi
}

oc-direct() {
  env -u OPENCODE_SERVER_USERNAME -u OPENCODE_SERVER_PASSWORD \
    command opencode --port=0 --hostname=127.0.0.1 "$@"
}

# ── Maintenance ──────────────────────────────────────────────────────

# _OC_VACUUM_SNAPSHOT_DAYS=7        max age (days) of snapshots before
#                                    cleanup during vacuum
_OC_VACUUM_SNAPSHOT_DAYS="${_OC_VACUUM_SNAPSHOT_DAYS:-7}"

# _OC_MEMWATCH_CRASH_MB=20000       RSS threshold for attach (MB) -
#                                    if exceeded, the process is killed
#                                    and a crash report is written.
# _OC_MEMWATCH_CHECK_INTERVAL=120   seconds between memory checks
# _OC_MEMWATCH_LOG_DIR              where crash reports are written
_OC_MEMWATCH_CRASH_MB="${_OC_MEMWATCH_CRASH_MB:-20000}"
_OC_MEMWATCH_CHECK_INTERVAL="${_OC_MEMWATCH_CHECK_INTERVAL:-120}"
_OC_MEMWATCH_LOG_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/opencode/memwatch"

_oc-memwatch() {
  local attach_pid max_mb interval logdir
  attach_pid="$1"
  max_mb="${2:-$_OC_MEMWATCH_CRASH_MB}"
  interval="${3:-$_OC_MEMWATCH_CHECK_INTERVAL}"
  logdir="$_OC_MEMWATCH_LOG_DIR"
  mkdir -p "$logdir"

  while kill -0 "$attach_pid" 2>/dev/null; do
    local rss_kb now
    rss_kb=$(ps -o rss= -p "$attach_pid" 2>/dev/null | tr -d ' ') || rss_kb=0
    now=$(date +%s)

    if (( rss_kb > max_mb * 1024 )); then
      local crash_file="$logdir/crash-${now}.txt"
      {
        echo "oc-memwatch crash at $(date -R)"
        echo "PID: $attach_pid  RSS: $(( rss_kb / 1024 )) MB  threshold: ${max_mb} MB"
        echo "--- ps ---"
        ps aux | grep '[o]pencode' 2>/dev/null
        echo "--- vm_stat ---"
        vm_stat 2>/dev/null | head -10
      } > "$crash_file"

      echo "[memwatch] RSS $(( rss_kb / 1024 )) MB exceeded ${max_mb} MB — killing PID $attach_pid" >&2
      kill "$attach_pid" 2>/dev/null
      exit 0
    fi

    sleep "$interval"
  done
}

oc-vacuum() {
  local db="${XDG_DATA_HOME:-$HOME/.local/share}/opencode/opencode.db"
  local snapshot_dir="${XDG_DATA_HOME:-$HOME/.local/share}/opencode/snapshot"

  if [[ ! -f "$db" ]]; then
    echo "No opencode database found at $db" >&2
    return 1
  fi

  local db_pids
  db_pids=$(lsof -t "$db" 2>/dev/null | tr '\n' ' ')
  if [[ -n "$db_pids" ]]; then
    echo "OpenCode database is in use (PID(s): $db_pids). All opencode processes must be stopped before vacuuming." >&2
    echo "Use: oc-stop && oc-vacuum && oc-tui" >&2
    return 1
  fi

  local before_size after_size

  echo "[$(date +%H:%M:%S)] vacuuming opencode database..." >&2
  before_size=$(_oc-stat-size "$db" 2>/dev/null) || before_size=0
  echo "  database size before: $(numfmt --to=iec "$before_size" 2>/dev/null || echo "${before_size} bytes")" >&2

  if ! command sqlite3 "$db" "VACUUM;" 2>/dev/null; then
    echo "  warning: VACUUM failed" >&2
    return 1
  fi

  after_size=$(_oc-stat-size "$db" 2>/dev/null) || after_size=0
  local reclaimed=$(( before_size - after_size ))
  echo "  database size after:  $(numfmt --to=iec "$after_size" 2>/dev/null || echo "${after_size} bytes")" >&2
  if (( reclaimed > 0 )); then
    echo "  reclaimed: $(numfmt --to=iec "$reclaimed" 2>/dev/null || echo "${reclaimed} bytes")" >&2
  fi

  if [[ -d "$snapshot_dir" ]]; then
    local count
    count=$(find "$snapshot_dir" -type d -mtime "+${_OC_VACUUM_SNAPSHOT_DAYS}" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' ')
    if (( count > 0 )); then
      echo "[$(date +%H:%M:%S)] removing ${count} snapshot(s) older than ${_OC_VACUUM_SNAPSHOT_DAYS} days..." >&2
      find "$snapshot_dir" -type d -mtime "+${_OC_VACUUM_SNAPSHOT_DAYS}" -mindepth 1 -maxdepth 1 -exec rm -rf {} \; 2>/dev/null
      echo "  done" >&2
    else
      echo "[$(date +%H:%M:%S)] no stale snapshots to remove" >&2
    fi
  fi

  echo "[$(date +%H:%M:%S)] vacuum complete" >&2
}
