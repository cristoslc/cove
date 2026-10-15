---
title: "AI-Git-Bot — self-hosted AI workflow automation platform for Git repositories"
type: web
url: "https://github.com/tmseidel/ai-git-bot"
fetched: 2026-10-14
license: MIT
language: en
---

# AI-Git-Bot

![Logo](doc/images/ai-git-bot-new-logo.png)

[![License: MIT](https://img.shields.io/github/license/tmseidel/ai-git-bot)](LICENSE)
[![Docker Pulls](https://img.shields.io/docker/pulls/tmseidel/ai-git-bot)](https://hub.docker.com/r/tmseidel/ai-git-bot)
[![GitHub release](https://img.shields.io/github/v/release/tmseidel/ai-git-bot)](https://github.com/tmseidel/ai-git-bot/releases)
[![GitHub stars](https://img.shields.io/github/stars/tmseidel/ai-git-bot)](https://github.com/tmseidel/ai-git-bot/stargazers)
[![GitHub issues](https://img.shields.io/github/issues/tmseidel/ai-git-bot)](https://github.com/tmseidel/ai-git-bot/issues)

🌐 Languages: **English** · [中文](README.zh.md) · [한국어](README.ko.md) · [日本語](README.ja.md)

> **The self-hosted AI workflow automation platform for Git repositories.**

- 🔍 Review pull requests
- 🧪 Generate tests
- ✏️ Improve issues
- 🧭 Triage and route new issues
- 🤖 Turn issues into pull requests
- 🎬 Create and run E2E tests
- 📝 Keep documentation in sync with the code
- 🌍 Keep translations in sync across locale files
- 💬 Answer questions inside code reviews
- 📊 Observe workflows via Prometheus metrics

## Why does this project exist?

Every engineering team has a list of things they know should happen:

- Pull requests should be reviewed carefully
- Bugs should get regression tests
- Issues should have acceptance criteria
- Documentation should stay up to date with the code
- Preview environments should be cleaned up
- Small maintenance tickets should eventually get implemented

Nobody disagrees with any of those ideas. The problem is that these tasks are:
* Uncomfortable
* Repetitive
* Difficult to prioritize
* Easy to postpone when deadlines get tight

AI-Git-Bot exists to turn these engineering chores into repeatable workflows that happen automatically inside your Git platform.

* No new development process.
* No migration project.
* No vendor lock-in.

Just better engineering hygiene through automation.

---

## Who is AI-Git-Bot for?

You may not fit neatly into a single category — many teams overlap across these concerns. Here are three illustrative examples:

### 🏢 Running Gitea and missing modern AI tooling?

Many teams choose Gitea because they want ownership of their source code and infrastructure.

Unfortunately, most AI products focus primarily on GitHub.

AI-Git-Bot brings:

- AI code reviews
- AI-generated tests
- AI issue authoring
- AI coding workflows
- AI documentation upkeep
- Interactive PR discussions

directly into Gitea.

Use OpenAI, Claude, Gemini or local Ollama models without forcing developers to leave their existing workflows.

👉 Think: **"Copilot-style workflow automation for Gitea."**

---

### 🔒 Need AI but cannot send source code to external services?

Many organizations cannot use cloud-only AI products due to compliance, privacy or contractual requirements.

AI-Git-Bot supports:

- Ollama
- llama.cpp
- Self-hosted Git platforms
- Private networks
- Provider-independent architectures

Source code, prompts, credentials and models remain under your control.

👉 Think: **"AI workflow automation without handing your repositories to a SaaS vendor."**

---

### 🚀 Maintaining repositories with too much engineering overhead?

Every engineering team has a list of things they know should happen. AI-Git-Bot turns those activities into repeatable workflows triggered by events your team is already producing:

- Pull request opened
- Pull request reopened
- New commits pushed (opt-in per bot)
- Reviewer requested
- Issue assigned
- `@bot` mentioned

👉 Think: **"The AI teammate that never forgets the boring but important work."**

---

💡 Already using GitHub Copilot?
> **Great.** Copilot helps developers write code faster. AI-Git-Bot helps teams automate reviews, tests, issues and pull-request workflows. Many teams use both.

## 🔌 Mix any AI provider with any Git platform

| AI providers | Git platforms |
|---|---|
| **Anthropic** (Claude) | **Gitea** (self-hosted) |
| **OpenAI** (+ OpenAI-compatible APIs) | **GitHub** / **GitHub Enterprise** |
| **Google AI / Gemini** | **GitLab** (gitlab.com & self-managed) |
| **Ollama** (local LLMs) | **Bitbucket Cloud** |
| **llama.cpp** (local GGUF models) | |

Unlike most AI coding tools, AI-Git-Bot is not tied to a specific Git platform or AI provider.

**Fully self-hostable. Your code can stay inside your infrastructure.**

---

## See it in action

AI-Git-Bot lives where your developers already work:

- GitHub
- GitHub Enterprise
- Gitea
- GitLab
- Bitbucket Cloud

1. Assign it a review.
2. Assign it an issue.
3. Mention it in a comment.
4. The bot responds directly inside your Git platform.

No extra dashboard. No browser extension. No Slack bot to babysit.

---

### Coding Agents

Assign an issue to a bot with the Coding Agent issue workflow and it can create an implementation pull request on your behalf.

---

## ✨ What can it do?

| Workflow | Trigger | Result |
|-----------|----------|---------|
| **PR Review** (doc/PR_WORKFLOWS_REVIEW.md) | PR opened or review re-requested | Review comments and findings |
| **Interactive Q&A** (doc/PR_WORKFLOWS_REVIEW.md) | `@bot` mention in PR comments | Context-aware conversation |
| **Issue → Code** (doc/CODING_AGENT.md) | Issue assigned to a bot with the Coding Agent issue workflow | Pull request |
| **Issue → Better Issue** (doc/WRITER_AGENT.md) | Issue assigned to a bot with the Writer Agent issue workflow | Structured issue with acceptance criteria |
| **Issue → Right Assignee** (doc/ISSUE_TRIAGE.md) | Issue opened or assigned to a bot with the Issue Triage issue workflow | Routing reason comment and issue assignment |
| **Issue Workflows** (doc/ISSUE_WORKFLOWS.md) | Configurable per bot | Pluggable issue-assigned behavior, independent from PR workflows |
| **Unit Test Generation** (doc/PR_WORKFLOWS_UNIT_TEST.md) | PR opened or command triggered | Generated tests committed to branch |
| **Full-Stack QA** (doc/PR_WORKFLOWS_E2E.md) | PR opened | Playwright suite executed against preview environment |
| **README Sync** (doc/PR_WORKFLOWS_README_SYNC.md) | PR opened or command triggered | Documentation updated to match code changes |
| **i18n Coverage** (doc/PR_WORKFLOWS_I18N_COVERAGE.md) | PR opened or command triggered | Missing translations drafted across locale files |
| **PR Re-Review** (doc/PR_WORKFLOWS_REVIEW.md) | Force-push or review request | Updated analysis |
| **Workflow Automation** (doc/PR_WORKFLOWS.md) | Git events | Automated engineering chores |
| **Prometheus Metrics** (doc/DEPLOYMENT.md#metrics-prometheus) | Built-in `/actuator/prometheus` endpoint | Operational metrics for reviews, findings, AI usage, errors, and tool calls |
| **Outgoing Webhooks** (doc/OUTGOING_WEBHOOKS.md) | Signed event push to external systems | Durable, retried HMAC-signed notifications for workflow runs, findings, and issue assignments |

---

## Current Workflows

### 🔍 Pull Request Reviews

Automatically review pull requests and provide:

- Summary findings
- Inline comments
- Suggested improvements
- Follow-up discussions

---

### 🧭 Issue Triage & Routing

Open an issue (or assign it to a bot with the Issue Triage issue workflow) and the bot decides who should own it.

Using an editable routing prompt, the bot:

1. Reads the issue
2. Chooses exactly one assignee from your configured accounts — a person, a bot, or `none`
3. Posts the routing reason as a comment
4. Assigns the issue (or leaves it unassigned for `none`)

---

### ✏️ Issue Refinement

Assign a bot with the Writer Agent issue workflow to an issue.

The bot transforms rough requirements into structured engineering work items containing:

- Background
- Requirements
- Acceptance criteria
- Implementation notes

---

### 🧪 Unit Test Generation

Generate white-box unit tests automatically based on pull request changes.

Tests can be validated using your project's own tooling before being committed.

---

### 🤖 Issue → Pull Request

Assign a bot with the Coding Agent issue workflow to an issue.

The bot:

1. Reads the issue
2. Clones the repository
3. Implements the change
4. Runs project validation
5. Opens a pull request

---

## Quick Start

### Quick testing

For a quick local test, run AI-Git-Bot with a single Docker command using the built-in H2 database and default settings:

```bash
docker run -p 8080:8080 tmseidel/ai-git-bot:latest
```

The image is published as a multi-arch manifest for **`linux/amd64`** and **`linux/arm64`**.

Then:

1. Open `http://localhost:8080`
2. Create your administrator account
3. Create an AI Integration
4. Create a Git Integration
5. Create a Bot
6. Configure the webhook
7. You're done

### Production deployment

For a configured production or long-term deployment, we recommend the Docker Compose approach, which gives you full control over configuration:

```bash
git clone https://github.com/tmseidel/ai-git-bot.git
cd ai-git-bot
docker compose up --build -d
```

See **[Deployment Guide](doc/DEPLOYMENT.md)** for detailed configuration instructions.

---

## Project Maturity

### Production-ready
* GitHub
* GitHub Enterprise
* Gitea

### 🧪 Community feedback welcome
* GitLab
* Bitbucket Cloud

### Experimental Workflows
⚠️ Full-Stack QA / E2E automation

## Technical Highlights

- 🔒 AES-256-GCM secret encryption when `APP_ENCRYPTION_KEY` is configured
- 🤖 Multi-provider AI support
- 🏢 Multi-platform Git support
- 🧠 Local LLM support
- 🔌 MCP integration
- 🧪 System-tested workflows
- 🐳 Docker-first deployment
- 🌍 Self-hostable end-to-end
- ♻️ Automatic retry with backoff when the AI provider reports itself overloaded (HTTP 503) — the affected PR or issue is told when the next attempt starts

## Community
* ⭐ >100 GitHub stars
* 🚀 >15 releases
* 🐳 Docker image available
* 🌍 Users across GitHub, Gitea, GitLab and Bitbucket

## Get started

```bash
docker pull tmseidel/ai-git-bot:latest
```

## License

[MIT](LICENSE)