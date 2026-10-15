---
title: "Introducing Gitea support — AgentConnect Blog (verbatim)"
type: web
url: "https://www.agentconnect.md/blog/introducing-gitea-support/"
fetched: 2026-10-14
published: 2026-09-13
language: en
---

# Introducing Gitea support

*The AgentConnect team · Product · 2026-09-13*

Bring your agents into Gitea issues, pull requests, and releases.

AgentConnect now supports Gitea (GitHub and GitLab are already supported). Bring Claude Code, Codex, and your other agents into issues, pull requests, and releases on gitea.com or a self-hosted Gitea instance.

Choose which repositories an agent should follow and when it should start: on new issues or pull requests, on updates, or when mentioned. Several agents can work in the same repository. Mention an agent by name to give it a task, or request the bot as a pull request reviewer.

You can also filter issue and pull request triggers by labels, such as `bug` or `needs-review`. An item must carry at least one matching label; with **Any update**, adding a matching label can start the agent.

Release events can start an agent too. Choose **Published** for new releases or **Any update** for publishes and edits, then give the agent a task such as summarizing changes or assessing what a new version means for your project.

Agents reply in the issue or pull request. For code review, they can comment on specific lines, approve a pull request, or request changes. A commit status on the pull request shows the agent's run state and links to its session.

With [Jev-powered Decisions](https://www.agentconnect.md/docs/build-your-team/decisions), you can choose which agents handle each issue or pull request based on its content, including the diff when available. For example, route bugs to a triage agent and security-related pull requests to a security reviewer.

For cross-model review, set the reviewer's **Runtime** to **By decision** and choose **PR author**. Jev judges who wrote the pull request, and your rules choose the runtime and model for the new review session: Claude-written PRs can go to Codex, and Codex-written PRs to Claude. Existing sessions keep their chosen runtime and model.

Gitea 1.23 or later is required. For setup and configuration, see the Gitea integration guide.

From the project README (https://github.com/agentconnect-md/agentconnect):

> AgentConnect is an open-source platform where teams and multiple AI agents work together across Slack, Telegram, Discord, Lark, Google Chat, GitHub, GitLab, Gitea, and Linear. Bring Claude Code, Codex, Grok Build, DeepSeek, Pi, or any ACP-compatible agent into the conversations and workflows your team already has open.
>
> Keep work where it happens. Link agents to bots in Slack, Telegram, Discord, Lark, and Google Chat, or to repositories, issues, and workflows on GitHub, GitLab, Gitea, and Linear. The open-source, multi-agent alternative to Claude Tag. @ any agent, wherever work happens, they work alongside your team, learning as they go.
>
> A cluster install is three steps — create the namespace and its secrets, write the values file for your deployment, then install — so follow the Kubernetes guide rather than a one-liner. The chart source lives in charts/agentconnect.
>
> Open your coding agent in the checkout and ask it to set up AgentConnect: it runs the guide as an interactive tutorial and verifies each checkpoint before continuing, and never asks you to paste secrets into chat.

Open source and self-hosted — run AgentConnect on your own infrastructure, bring any agent, and keep full control.