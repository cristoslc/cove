# DNS as Cove Infrastructure

Cove's dnsmasq service currently does exactly one thing: `address=/cove/127.0.0.1` — a single wildcard that resolves every `*.cove` name to `127.0.0.1`. This is already more powerful than it looks. Because the wildcard covers *everything* under `.cove`, any name you invent — `myapp.site.cove`, `db.myapp.cove`, `staging.api.cove` — already resolves. You don't need to register it. The DNS layer is fully general right now.

The gap isn't DNS. It's what happens after resolution.

## What Works Today

```
dig myapp.site.cove @127.0.0.1 -p 5353    → 127.0.0.1  ✓
dig db.myapp.cove @127.0.0.1 -p 5353      → 127.0.0.1  ✓
dig anything.you.invent.cove @127.0.0.1 -p 5353 → 127.0.0.1  ✓
```

Every `*.cove` name resolves. The wildcard is already infinite. No CLI command needed, no registration, no config file. You invent a name, it resolves.

## What Doesn't Work

nginx has no server block for `myapp.site.cove`. The request hits the catch-all (`server_name _`) and proxies to Forgejo. You get Forgejo's login page at `https://myapp.site.cove/`. That's confusing and wrong.

The DNS layer is general. The routing layer is hardcoded to Cove's four known services.

## The Real Question

Should Cove provide routing for user-defined hostnames, or is that the user's responsibility?

### Option A: DNS only (Cove's job ends at resolution)

Cove resolves any `*.cove` name. What happens at the HTTP layer is the user's problem. They can:
- Run their own reverse proxy (Caddy, nginx, Traefik) that listens on a different port and routes `myapp.site.cove` to their app
- Add server blocks to Cove's nginx template (edit `default.conf.j2`, re-render, restart nginx)
- Use `extra_hosts` in their own docker-compose files to make containers resolve `db.myapp.cove`

This is the cleanest scope boundary. Cove provides DNS infrastructure. The user provides everything above layer 3.

**Problem:** "Just run your own reverse proxy" is friction. The user already has nginx running with valid TLS for `*.cove`. Running a second reverse proxy means either a port conflict or a non-standard port. Editing Cove's nginx template means their changes get clobbered on `cove up`.

### Option B: nginx include directory

Cove's nginx config adds an `include /etc/nginx/user.d/*.conf;` directive. Users drop server block files into a directory. Cove never touches them.

```
~/Documents/cove-data/nginx/user.d/
├── myapp.conf     # server { server_name myapp.site.cove; proxy_pass http://host.docker.internal:3000; }
└── myapp-db.conf  # server { server_name db.myapp.cove; proxy_pass http://host.docker.internal:5432; }
```

nginx reloads on SIGHUP. `cove up` doesn't clobber user files. The TLS cert already covers `*.cove` (wildcard SAN), so any subdomain gets valid HTTPS for free.

**This is the sweet spot.** Cove provides:
1. DNS resolution for any `*.cove` name (already works)
2. TLS termination for any `*.cove` name (already works — wildcard cert)
3. A drop-in directory for user-defined routes (new, trivial to add)

The user provides:
1. The server block file
2. The service behind it (their app, their database proxy, whatever)

### Option C: CLI-managed routes

`cove route add myapp.site.cove --to localhost:3000` writes the nginx server block and reloads. `cove route list`, `cove route remove`. Clean UX but adds CLI surface and couples Cove to the routing layer. Overengineered for "drop a file in a directory."

## What About Non-HTTP Services?

`db.myapp.cove` resolving to `127.0.0.1` is useful even without nginx. A Postgres client on the host can connect to `db.myapp.cove:5432` if Postgres is running on the host. A container with `extra_hosts: db.myapp.cove:host-gateway` can resolve it. DNS alone enables this — no nginx needed.

For TCP services that aren't HTTP, DNS resolution is the entire value. Cove already provides it.

## Implementation (Option B)

Three changes, all trivial:

### 1. nginx config template (`default.conf.j2`)

Add one line at the top of the http block (or at the end of the file, before any conditional blocks):

```nginx
include /etc/nginx/user.d/*.conf;
```

### 2. docker-compose.yml

Add a volume mount for the user.d directory:

```yaml
nginx:
  volumes:
    - ${COVE_DATA_ROOT}/nginx/user.d:/etc/nginx/user.d:ro
```

### 3. bringup.yml

Add the directory to the data dirs task:

```yaml
- "{{ cove_data_root }}/nginx/user.d"
```

That's it. Three lines changed. Zero new CLI surface. Zero new services. The user drops a `.conf` file in `~/Documents/cove-data/nginx/user.d/` and sends SIGHUP to nginx (`docker kill -s HUP cove-nginx`).

## Example: Local Webapp + Database

User is building a Next.js app on port 3000 and has Postgres on 5432. They want `myapp.site.cove` for the app and `db.myapp.cove` for the database.

**DNS:** Already works. Both names resolve to `127.0.0.1`.

**For the database:** Nothing needed. `psql -h db.myapp.cove` works because DNS resolves and Postgres is on the host.

**For the webapp:** Drop this in `~/Documents/cove-data/nginx/user.d/myapp.conf`:

```nginx
server {
    listen 443 ssl;
    server_name myapp.site.cove;

    ssl_certificate     /certs/cove.local.pem;
    ssl_certificate_key /certs/cove.local-key.pem;

    location / {
        proxy_pass http://host.docker.internal:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

Reload: `docker kill -s HUP cove-nginx`. Done. `https://myapp.site.cove/` serves the Next.js app with valid TLS, no browser warnings, no port numbers in the URL.

## Scope Boundary

This is the right line:

| Layer | Owner | Mechanism |
|-------|-------|-----------|
| DNS resolution (`*.cove` → `127.0.0.1`) | Cove | dnsmasq wildcard |
| TLS termination (valid cert for `*.cove`) | Cove | mkcert wildcard + nginx |
| HTTP routing (which hostname → which backend) | User | nginx user.d drop-in |
| The actual service (app, database, proxy) | User | Their own process/container |

Cove provides the first two layers universally — any `*.cove` name gets DNS + TLS for free. The user provides the last two — what the name routes to and what's running there. The `user.d` directory is the handoff point.

## What This Is Not

- **Not a service mesh.** Cove doesn't manage the services behind the hostnames.
- **Not a discovery mechanism.** Cove doesn't know what's running on port 3000.
- **Not a replacement for docker-compose networking.** Containers on the same compose network should use Docker's internal DNS (`service-name:port`). `*.cove` names are for host→container and container→host communication.
- **Not a production pattern.** `host.docker.internal` is a development convenience. In production you'd proxy to a container name, not the host.

## Relationship to Pages

Pages already uses this pattern: `*.pages.cove` resolves via dnsmasq, nginx has a regex server block that routes by subdomain, and the content comes from a data directory. The `user.d` directory extends the same pattern to user-owned services — instead of serving static files from a data directory, it proxies to a user-specified backend.

## Open Questions

1. **Should `cove up` create a skeleton `user.d/` with an example file?** A commented-out example would teach the pattern without being active. Low priority, but helpful for discovery.

2. **Should nginx reload be automated?** A `cove route reload` command or a file watcher that SIGHUPs nginx when `user.d/` changes. Not necessary — `docker kill -s HUP cove-nginx` is one command — but would polish the experience.

3. **What about non-localhost backends?** `proxy_pass http://host.docker.internal:3000` works for host services. For container services on the same Docker network, `proxy_pass http://container-name:port` works. For external services, `proxy_pass https://real-service.example.com` works. The user.d file is just nginx config — anything nginx can proxy, it can route.

4. **Should `*.cove` wildcard DNS be documented more prominently?** The architecture doc mentions it, but the "any name you invent resolves" property isn't surfaced as a feature. It should be.
