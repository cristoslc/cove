# Version bump PR body template
#
# Used by the planned `version-audit` workflow and by manual bump PRs; the
# BB reviewer automation parses the evidence block mechanically. Fill every
# field; None is an explicit answer, omission is not.

## Evidence

- **Component:**
- **Upstream release:** (link to release notes / changelog)
- **Old pin:** (ref, and digest if present)
- **New pin:** (ref, and digest if present)
- **Classification:** patch | minor | major (with the semver change that drives it)
- **Security advisories:** (links, or "None checked against current pin")
- **SBOM delta:** (attached `sbom/<component>.cdx.json` diff summary)
- **Test gates:** unit gate result; tier-2 staging result (required before merge)

## Notes

(gap analysis for a major; migration steps if any; or "None")