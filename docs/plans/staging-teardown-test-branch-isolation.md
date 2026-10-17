# Plan: Make the staging teardown overlap test branch-independent

## Problem

The required non-E2E test gate runs from the repository's `main` checkout. The overlap regression test invokes `scripts/staging/teardown.sh` from the current checkout, so the script's intentional main-branch safety guard exits before the test reaches its data-root overlap assertion.

## Goal

Run the overlap check in an isolated temporary Git repository on a controlled non-production branch, and cover the main-branch guard independently. The test suite must pass from either `main` or a feature worktree without weakening teardown safety.

## Approach

Copy the teardown script into a temporary repository fixture, initialize that fixture on an explicit branch, and run it there with fake Docker and isolated data roots. Keep the production script unchanged unless the fixture exposes a real behavior defect.

## Acceptance

- The overlap test reaches the overlap guard from an explicit non-main branch and preserves a live-root sentinel.
- A separate test confirms the main branch guard refuses teardown before touching data.
- Focused staging isolation tests and the required non-E2E/non-staging gate pass.
- The change is submitted as a draft Forgejo PR to `main`; no merge, release, install, or live service action occurs.
