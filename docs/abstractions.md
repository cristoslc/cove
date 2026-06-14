---
title: Cove Abstractions
created: 2026-05-09
authored-by: deepseek-v4-pro:cloud
status: Active
---

# Cove Abstractions

The domain concepts that describe Cove's problem space. For the bounded contexts that own them, see the [Bounded Contexts](architecture.md#bounded-contexts) section of the architecture.

## Forge Context

### Project

A thing you are building. A git repository with an optional build configuration (Dockerfile, docker-compose.yml, Hugo config, etc.). Projects are the unit of work — you clone them, you push them, you build them, you deploy them. Cove does not own your projects. It provides the harbor they run in.

A project is also the unit of identity: `<owner>/<repo>`. Every URL, artifact path, and pages site derives from this identity. Projects exist in the forge but are referenced from every other context.

### Pipeline

A sequence of steps that transforms source code into a deployable artifact. Written as a `.forgejo/workflows/*.yml` file. Runs in response to a git event (push, tag). A pipeline is Cove's equivalent of "build and deploy" — it replaces manual `docker build && docker run` with a reproducible, triggered sequence.

Pipelines are portable. The only difference between a Cove pipeline and its GitHub counterpart is the `uses:` line for actions. Everything else — triggers, inputs, outputs, environment variables — is identical.

## Vault Context

### Secret

A piece of information a pipeline or service needs that must not live in source code. Secrets move through four stages: source of truth (1Password) → disk cache (`cove creds batch-pull`) → Vault cache (KV v2) → consumer (pipeline step, Ansible task, CLI). The canonical address is an `op://` reference. Vault holds the cache so pipelines run offline. Consumers call `cove creds vault-get` and receive a string — they never know which stage produced it.

## Registry Context

### Image

A built container, stored as an OCI artifact in Forgejo's container registry. Images are what pipelines produce when the build target is a Dockerfile. They are identified by `<owner>/<name>:<tag>` and pushed to `https://git.cove/v2/`. They serve as the input to container deployments. Forgejo's registry stores both locally built and externally pulled images, making them available to authenticated consumers.

## Pages Context

### Site

A deployed static website. Identified by `<owner>` (the forge identity) and optionally `<repo>` (for project-specific sites). A user or organization has exactly one index site (from a repo named `pages`) and zero or more project sites. Sites are the output of a pipeline that builds static content (Hugo, Zola, plain HTML) and deploys it to the pages server.

### Deployment

The act of making an artifact available. Deployments answer "where is this running?" — at a URL, behind a subdomain. A deployment is created by a pipeline's deploy step and torn down by `cove down` or by re-deploying. Deployments are ephemeral; the artifact (image or site) is what persists.

Two forms:
- **Platform deployments** — Forgejo, Vault, nginx, dnsmasq. Always running. Provisioned by Ansible, not by pipelines.
- **Project deployments** — static sites, tryout projects, custom services. Created and destroyed by pipelines or CLI commands.

## Cross-Cutting

### Identity

The `<owner>/<repo>` tuple that names a project. Originates in the forge, flows into every other context — Vault (secret paths scoped by identity), Registry (image namespaces), Pages (subdomains and site directories), Runtime (job context). Every Cove artifact can be traced back to the project that produced it.

### Workspace

The filesystem context where development happens. A workspace is `~/Documents/projects/<project>/` — a directory on the host containing source code, visible to containers via bind mounts. Workspaces are the bridge between "editing code in an IDE" and "running it in the harbor." The CLI operates on the current workspace by default. Workspaces are the host-side reflection of a Project — one is local, the other lives in the forge.
