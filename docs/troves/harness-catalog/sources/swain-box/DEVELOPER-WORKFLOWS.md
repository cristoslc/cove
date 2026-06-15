# DEVELOPER-WORKFLOWS.md

## Local dev — VM lifecycle

```bash
# Start
limactl start opencode-dev

# Shell into VM
limactl shell opencode-dev

# Stop (keeps disk)
limactl stop opencode-dev

# Delete entirely
limactl delete opencode-dev
```

## Deploy

There is no deployment pipeline beyond `limactl start`. VM provisioning runs the install scripts defined in the YAML `provision` block.

## Data management

- VM writes opencode DB to `~/lima-opencode-data/` (host mount)
- Host runs ccusage against same directory
- Always stop the VM before deleting data

See `docs/developer-workflows/` for full detail.