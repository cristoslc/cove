# Non-HTTP Services and DNS

Cove's DNS infrastructure handles HTTP services through nginx routing (server blocks, `user.d` include directory). But DNS resolution itself is protocol-agnostic — `db.myapp.cove` resolving to `127.0.0.1` works for Postgres, Redis, SSH, or any TCP/UDP service. No nginx needed. No reverse proxy. No TLS termination. Just name resolution.

## What Already Works

Any `*.cove` name resolves. A Postgres client on the host can connect to `db.myapp.cove:5432` if Postgres is running on the host. A container with `extra_hosts: db.myapp.cove:host-gateway` can resolve it. A remote machine with a resolver file for `cove.mbpbk` can connect to `db.myapp.cove.mbpbk:5432` if Postgres is running on the MacBook.

```
psql -h db.myapp.cove -p 5432           # host → host Postgres
psql -h db.myapp.cove.mbpbk -p 5432     # remote → MacBook's Postgres
redis-cli -h cache.myapp.cove -p 6379   # host → host Redis
ssh git.cove.mbpbk -p 2222              # remote → MacBook's Forgejo SSH
```

DNS alone enables all of this. No additional Cove infrastructure needed.

## The Gap: Port Discovery

DNS resolves names to IPs. It doesn't tell you the port. `db.myapp.cove` resolves to `127.0.0.1`, but the client still needs to know port 5432. For HTTP, the convention is port 443 (and nginx handles routing). For non-HTTP, the port is service-specific and the client must already know it.

### SRV Records

dnsmasq supports SRV records, which encode both host and port:

```
srv-host=_postgres._tcp.cove,db.myapp.cove,5432,0,0
srv-host=_redis._tcp.cove,cache.myapp.cove,6379,0,0
```

A client that understands SRV records can discover the port:

```
dig SRV _postgres._tcp.cove @127.0.0.1 -p 5353
→ db.myapp.cove:5432
```

But most database clients don't do SRV lookups. PostgreSQL's `libpq` doesn't. Redis CLI doesn't. MySQL doesn't. SRV is used by protocols that were designed for it (SIP, XMPP, LDAP, some HTTP/2) — not by databases.

SRV records in dnsmasq are technically possible but practically useless for the services people actually run. The port is always known by the client.

## What Cove Should Do

**Nothing.** DNS resolution for non-HTTP services is already complete. The name resolves, the client connects on the known port. Cove doesn't need to know about the service, route it, or discover it.

The `user.d` nginx include directory is for HTTP routing. Non-HTTP services don't need it. The `/config/` page lists Cove's own services (forge, vault). User services are the user's responsibility — Cove provides the DNS layer, the user provides the service and knows the port.

## What This Is Not

- **Not a service mesh.** Cove doesn't manage non-HTTP backends, doesn't do health checks on them, doesn't route or load-balance them.
- **Not a discovery mechanism.** Cove doesn't know what's running on port 5432. The operator knows.
- **Not a port registry.** No `cove service register db --port 5432` command. The port is in the connection string, where it belongs.

## The Line

| Layer | Owner | Mechanism |
|-------|-------|-----------|
| DNS resolution (`*.cove` → IP) | Cove | dnsmasq wildcard + resolver files |
| HTTP routing (hostname → backend) | Cove (own services) or User | nginx server blocks |
| HTTP TLS termination | Cove | nginx + mkcert |
| Non-HTTP connection | User | Direct — client connects to resolved IP on known port |

nginx is the ingress for HTTP. Non-HTTP services bypass nginx entirely. DNS resolves `db.myapp.cove` to `127.0.0.1`, the Postgres client connects to `127.0.0.1:5432` directly. nginx never sees the connection. Same for Redis, SSH, or any TCP/UDP service — DNS provides the name, the client provides the port, the connection is direct.
