---
type: intent
timestamp: 2026-10-16T235700
responding-to: security review of config validation
---

## Broaden secret field validation

Per operator request: I will ensure common provider credential field names, including compound names such as `aws_secret_access_key`, require environment references rather than YAML literals. Success means tests cover these names and the full non-E2E/non-staging gate remains green.
