# Ansible Deprecation Warnings

## Symptom

Every `cove up` run floods stderr with:

```
[DEPRECATION WARNING]: INJECT_FACTS_AS_VARS default to `True` is deprecated,
top-level facts will not be auto injected after the change. This feature will
be removed from ansible-core version 2.24.
```

One instance per unique Jinja2 template or `when` condition that references
`ansible_system`, `ansible_env.HOME`, `ansible_hostname`, etc. — roughly 20+
warnings per run.

## Root Cause

Ansible 2.18 deprecated the automatic injection of gathered facts as
top-level variables. Previously, `ansible_system` was available directly;
the new canonical form is `ansible_facts["system"]`. The default value of
`INJECT_FACTS_AS_VARS` remains `True` for backward compatibility, but the
deprecation warning fires for every reference to a bare fact name.

The warning is about the *default changing*, not about the value being wrong.
Setting `inject_facts_as_vars = True` explicitly in `ansible.cfg` silences it
entirely — you're just stating the intent clearly.

## Fix

Add an `ansible.cfg` alongside the playbooks in the compose bundle:

```ini
[defaults]
inject_facts_as_vars = True
deprecation_warnings = False
```

`deprecation_warnings = False` is a belt-and-suspenders: it suppresses any
other ansible-core deprecation noise that might appear in the future. The
`inject_facts_as_vars = True` is the semantically correct opt-in.

## Future (ansible-core 2.24+)

When 2.24 removes the feature entirely, `inject_facts_as_vars = True` will
become a no-op (the setting will be ignored). At that point we must migrate
every reference:

| Before | After |
|---|---|
| `ansible_system` | `ansible_facts["system"]` |
| `ansible_env.HOME` | `ansible_facts["env"]["HOME"]` |
| `ansible_hostname` | `ansible_facts["hostname"]` |
| `ansible_user_id` | `ansible_facts["user_id"]` |
| `ansible_default_ipv4.address` | `ansible_facts["default_ipv4"]["address"]` |
| `ansible_date_time.epoch` | `ansible_facts["date_time"]["epoch"]` |
| `ansible_user_uid` | `ansible_facts["user_uid"]` |
| `ansible_user_gid` | `ansible_facts["user_gid"]` |

This touches every `.j2` template, every `when` condition, and every
`group_vars/all.yml` reference. Best done as a single mechanical pass when
we actually upgrade ansible-core.

## Tradeoff

The `ansible.cfg` approach is minimal-touch and zero-risk. The alternative
— migrating all refs now — would be correct but noisy and risky (typos in
fact names cause silent failures). Since the deprecation window is generous
(2.24 is not yet released), deferring the migration is pragmatic.
