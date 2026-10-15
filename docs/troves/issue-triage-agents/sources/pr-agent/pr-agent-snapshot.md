---
title: "PR-Agent README (verbatim)"
type: web
url: "https://github.com/The-PR-Agent/pr-agent"
fetched: 2026-10-14
license: Apache-2.0
---

# PR-Agent

The Original Open-Source PR Reviewer

This repository contains the open-source PR Agent Project. It is not the Qodo offering for open-source projects.

PR-Agent is an open-source, AI-powered code review agent and a community-maintained legacy project of Qodo. It is distinct from Qodo's primary AI code review offering, which provides a feature-rich, context-aware experience.

## Getting Started

> **Docker Hub namespace migration.** Releases `0.34.2` and later are published under [`pragent/pr-agent`](https://hub.docker.com/r/pragent/pr-agent). Older releases remain available at the legacy [`codiumai/pr-agent`](https://hub.docker.com/r/codiumai/pr-agent) namespace as a frozen archive.

### 1. GitHub Action (Recommended)

```yaml
# .github/workflows/pr-agent.yml
name: PR Agent
on:
  pull_request:
    types: [opened, synchronize]
jobs:
  pr_agent_job:
    runs-on: ubuntu-latest
    steps:
    - name: PR Agent action step
      uses: the-pr-agent/pr-agent@main
      env:
        OPENAI_KEY: ${{ secrets.OPENAI_KEY }}
        GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### 2. CLI Usage (Local Development)

```bash
pip install "pr-agent[github]"
export OPENAI_KEY=your_key_here
pr-agent --pr_url https://github.com/owner/repo/pull/123 review
```

Git provider SDKs are optional extras: install the one for your provider, or `pr-agent[all]` for every integration.

### 3. Other Platforms

- GitLab webhook setup, BitBucket app installation, Azure DevOps setup.

## Why Use PR-Agent?

**Fast & Affordable**: Each tool (`/review`, `/improve`, `/ask`) uses a single LLM call (~30 seconds, low cost)

**Handles Any PR Size**: PR Compression strategy effectively processes both small and large PRs

**Highly Customizable**: JSON-based prompting allows easy customization of review categories and behavior via configuration files

**Platform Agnostic**:
- **Git Providers**: GitHub, GitLab, BitBucket, Azure DevOps, Gitea
- **Deployment**: CLI, GitHub Actions, Docker, self-hosted, webhooks
- **AI Models**: OpenAI GPT, Anthropic Claude, Google Gemini, DeepSeek, Mistral, and any other model reachable through LiteLLM (Azure OpenAI, AWS Bedrock, Vertex AI, Databricks, OpenRouter, Ollama, and more)

**Open Source Benefits**: Full control over your data and infrastructure; customize prompts and behavior; no vendor lock-in; community-driven development.

## Features

See the current feature and git provider support matrix at https://docs.pr-agent.ai/overview/supported_platforms/

⚠️ `/help_docs` is temporarily disabled since `v0.36.1` pending a fix for a credential-exposure issue (#2445).

## See It in Action

### Usage Examples

PR-Agent tools run as a comment on a PR or from the CLI:

```bash
# Comment on a PR (GitHub/GitLab/Bitbucket/…):
/describe
/review
/improve
/ask "What does this PR change?" # free-text Q&A about the PR

# Issue-scoped commands run on an issue instead of a PR:
/similar_issue # find similar issues in the repository

# Or locally via the CLI:
pr-agent --pr_url <PR_URL> review
pr-agent --issue_url <ISSUE_URL> similar_issue
```

## Data Privacy

### Self-hosted PR-Agent
- If you host PR-Agent with your OpenAI API key, it is between you and OpenAI.

## Contributing

For local verification, run `PYTHONPATH=. uv run pytest` from the repository root; it discovers the unit-test suite under `tests/unittest` by default. End-to-end tests under `tests/e2e_tests` require provider credentials and should be invoked explicitly.

## Big News for PR-Agent

PR-Agent has a new home! Qodo has donated PR-Agent to the open-source community. The project now lives in the PR-Agent org on GitHub, is fully community-owned, and is open for contributions and additional maintainers. Docs moved to docs.pr-agent.ai. The project now has its first external maintainer, Naor (@naorpeled), and is currently in the process of being donated to an open-source foundation.