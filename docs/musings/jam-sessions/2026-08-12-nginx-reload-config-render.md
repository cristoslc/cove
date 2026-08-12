# Jam: nginx reload on config render

Date: 2026-08-12
Desc: Cove status page now has a Pages card → pages list page; jam on making `cove up` apply nginx config changes automatically.

## 2026-08-12 — Added Pages card + pages list page

- What: Added `pages.cove.local` portal (`compose/nginx/pages.html` + `compose/nginx/cove-pages-locations.conf` autoindex JSON API) and a Pages card on `landing.html`. Wired into `default.conf.j2`, `docker-compose.yml`, `bringup.yml` hosts, coverage matrix.
- Result: Card initially showed nothing — my manual edit to `compose/nginx/default.conf` was overwritten when the generated file was re-rendered from `.j2`.
- Next: Confirm `cove up` re-renders and auto-applies nginx config; if not, add a reload step.

## 2026-08-12 02:5x — Root cause: default.conf is a generated artifact

- What: Verified `bringup.yml` renders `default.conf.j2` → `compose/nginx/default.conf` unconditionally (template task). The `.conf` is gitignored. nginx only reads config at startup/reload, and `docker compose up -d` won't recreate nginx just for a mounted-file change. So a `.j2` edit + `cove up` re-renders the file but does NOT apply it to the running nginx.
- Result: Manual `.conf` edit lost; after regenerating `.conf` and `nginx -s reload`, the pages page worked end-to-end (`pages.cove.local` 200, `/api/owners/` JSON, `alice.pages.cove.local/docs/` served).
- Next: Add an nginx reload step to bringup.yml so `cove up` applies template changes automatically.

## 2026-08-12 14:4x — Added nginx reload handler to bringup.yml

- What: Added `notify: Reload nginx` to the "Render nginx config from template" task and a `handlers:` block at the end of the play that runs `docker exec {{ nginx_container_name }} nginx -s reload` (with `DOCKER_HOST` from the registered `docker_host_detect`). Handlers run at end of play, after `docker compose up`, so nginx is up when the reload fires.
- Result: `ansible-playbook --syntax-check` passes; YAML valid; `docker exec cove-nginx nginx -s reload` verified working against the live container. `cove up` will now auto-apply nginx template changes.
- Next: (jam winding down) squash checkpoints, close log.
