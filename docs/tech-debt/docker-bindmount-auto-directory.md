# Docker bind-mounts auto-create directories before files are rendered

**Found:** 2026-09-04, during `cove up` failure on MBPBK-202602
**Status:** Partially hardened — bringup.yml now fails loudly for the mount targets it renders. Residual risk tracked below.

## Failure mode

Docker bind-mounts auto-create a missing host path as a **directory**. If
`docker compose up` runs before a file-mount target is rendered on disk (e.g. a
failed first boot, or a run where template rendering was skipped), the target
becomes an empty directory. Every later attempt to mount the real file onto it
fails with:

```
OCI runtime create failed: ... error mounting ".../default.conf" to rootfs at
"/etc/nginx/conf.d/default.conf": ... not a directory: Are you trying to mount
a directory onto a file (or vice-versa)?
```

Worse, the Ansible `template` task then writes the rendered file **inside** the
directory (`default.conf/default.conf.j2`) and still reports "changed",
masking the problem.

## Hardening applied

`compose/bringup.yml` now has two guard tasks before the TEMPLATES section:

- `Assert nginx bind-mount targets are not directories` — stats
  `default.conf`, `landing.html`, `pages.html`, `cove-config-locations.conf`,
  `cove-pages-locations.conf` under `nginx_conf_dir`.
- `Assert data-root bind-mount targets are not directories` — stats
  `dnsmasq/cove.conf`, `nginx/config.html`, `litellm/config.yaml` under
  `cove_data_root`.

If any exists as a directory, the playbook fails loudly with the exact
remediation (`rm -rf <path> && cove up`).

## Residual risk (this debt)

The guard covers the mount targets bringup itself renders. Two gaps remain:

1. **Render-after-compose ordering is still not guaranteed.** The real fix is
   to never run `docker compose up` before all file-mount targets exist on
   disk — i.e. render templates first, then compose. Today the render tasks
   are in the same play before the compose task, so ordering is correct, but
   any new file mount added to `docker-compose.yml` needs a corresponding
   entry in the guard list (and its render task must precede compose up).
   There is no automated check binding compose file-mounts to the guard list;
   drift between the two is possible.
2. **Non-rendered file mounts.** `certs/rootCA.pem` is copied by bringup, but
   any future mount sourced outside the TEMPLATES section (e.g. hand-seeded
   or CLI-provisioned files) won't be covered unless added to a guard.

## Follow-up options

- A test that parses `docker-compose.yml` file-mounts and asserts each host
  path appears in one of the guard lists (catches drift).
- Or: a pre-compose task that converts any directory at a file-mount target
  into the correct rendered file, instead of failing.

Related: `extract-resources-deletes-env.md` (same class: runtime compose dir
is a cache regenerated from the wheel, stale artifacts can wedge boots).