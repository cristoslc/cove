# ASF Workflow / Scheduling / Job-Runner Landscape

Date: 2026-07-06
Trigger: research request for Apache Software Foundation projects relevant to workflow orchestration, scheduling, job runners, and cron replacements.

## Scope

Researched all ASF projects (active TLPs, retired, incubating, retired podlings) that touch:
- Workflow orchestration
- Job scheduling / batch scheduling
- Cron replacement / lightweight job runners
- Scheduled script execution
- Distributed task frameworks

Compared against Dagu's defining traits (single binary, YAML DAGs, file-backed, no DBMS, local-first).

## Projects verified (user already knew)

### 1. Apache Airflow — TLP, active

- **Status:** Top-Level Project (graduated Dec 2018). https://incubator.apache.org/projects/airflow.html
- **What it does:** Programmatically author, schedule, and monitor workflows as Python DAGs. De facto standard for data pipeline orchestration. https://airflow.apache.org/
- **License:** Apache 2.0. https://airflow.apache.org/docs/apache-airflow/stable/license.html
- **Architecture:** Requires metadata DB (PostgreSQL/MySQL/SQLite dev). Distributed via Celery/Kubernetes executors, or local SequentialExecutor. Scheduler + webserver + executor + metastore. Not a single binary.
- **Workflow format:** Code — Python DAGs.
- **Commercial managed tier:** Multi-vendor. Astronomer (Astro), Google Cloud Composer, Amazon MWAA. The most commercialized ASF project in this space. https://medium.com/apache-airflow/managed-apache-airflow-c361f4c8a4e1
- **Community health:** Very high. Airflow 3.x shipped 2025; regular releases through 2026. Thousands of contributors, hundreds of providers. https://github.com/apache/airflow
- **Fit for single-dev local-offline:** Marginal. Can run standalone with SQLite + SequentialExecutor, but heavyweight (Python deps, webserver, scheduler). Workable for one developer but overkill vs. cron/Dagu. Enterprise-grade at heart.

### 2. Apache DolphinScheduler — TLP, active

- **Status:** Top-Level Project (graduated 2021). https://dolphinscheduler.apache.org/
- **What it does:** Distributed workflow orchestration with drag-and-drop visual DAG UI, low-code. Originally "EasyScheduler" by Analysys (China). Targets big-data ETL scheduling. https://news.apache.org/foundation/entry/asf-project-spotlight-apache-dolphinscheduler
- **License:** Apache 2.0.
- **Architecture:** Decentralized multi-master/multi-worker. Requires PostgreSQL/MySQL + ZooKeeper. Java. Four deploy modes: Standalone, Cluster, Docker, K8s. https://deepwiki.com/apache/dolphinscheduler
- **Workflow format:** Visual (drag-drop) + Python SDK + Open API. Not YAML-first.
- **Commercial managed tier:** Effectively single-vendor / community-driven. Originated at Analysys; no Western cloud managed offering. Some Chinese vendors offer support. Not multi-vendor in the Airflow sense.
- **Community health:** Active. ~10k+ GitHub stars, regular releases (3.x line), active commits. Smaller than Airflow and more China-centric. https://github.com/apache/dolphinscheduler
- **Fit for single-dev local-offline:** Poor. Standalone mode exists but still needs a DB; JVM app designed for cluster scaling. Overkill for local scripting.

### 3. Apache NiFi — TLP, active (but wrong category)

- **Status:** Top-Level Project. https://nifi.apache.org/
- **What it does:** Flow-based data movement/routing/transformation engine. NOT a general workflow orchestrator — moves data between systems with a visual UI. Each processor has timer-driven or cron-driven scheduling for when it pulls/pushes, but it's data-flow scheduling, not job-DAG scheduling. https://nifi.apache.org/docs/nifi-docs/html/user-guide.html
- **License:** Apache 2.0.
- **Architecture:** Java. Single node or cluster. Requires a DB (H2/Postgres) for flowfile/provenance repositories. Not a single binary. https://tasrieit.com/blog/apache-nifi-vs-airflow-2026
- **Workflow format:** Visual drag-drop of processors on a canvas. No code, no YAML.
- **Commercial managed tier:** Single-vendor dominant. Cloudera DataFlow (CDF) is the primary commercial offering. https://www.cloudera.com/products/open-source/apache-hadoop/apache-nifi.html Datavolo (founded by NiFi creators) was acquired by Snowflake.
- **Community health:** Active, mature, large. Regular releases.
- **Fit for single-dev local-offline:** Poor. Wrong tool — it's for streaming/integration, not cron-replacement. Heavy JVM stack.
- **Verdict:** NiFi has scheduling primitives but is a data pipeline / data flow tool, not a workflow scheduler in the Airflow sense. Different category.

### 4. Apache SeaTunnel — TLP, active (not a scheduler)

- **Status:** Top-Level Project (graduated 2022). https://seatunnel.apache.org/
- **What it does:** Multimodal high-performance data integration tool (CDC, batch, streaming sync). Moves data between sources and sinks. https://github.com/apache/seatunnel
- **License:** Apache 2.0.
- **Architecture:** Distributed. Runs on its own Zeta engine, Flink, or Spark. JVM.
- **Workflow format:** HOCON/DSL config + optional canvas UI (via seatunnel-web).
- **Commercial managed tier:** No major managed tier. Community + Chinese cloud vendors. Users include JP Morgan, ByteDance, Tencent Cloud.
- **Community health:** Active, growing. https://seatunnel.apache.org/docs/about/
- **Fit for single-dev local-offline:** Poor. It's data integration, not scheduling. Its own FAQ explicitly says: "use Linux cron jobs… or leverage scheduling tools like Apache DolphinScheduler or Apache Airflow to manage complex scheduled tasks." https://seatunnel.apache.org/docs/faq
- **Verdict:** SeaTunnel is not a scheduler. It's an ETL/CDC engine that needs an external scheduler.

## Projects you missed

### 5. Apache Oozie — RETIRED (Feb 2025)

- **Status:** Retired February 2025 (moved to Attic). https://www.mail-archive.com/announce@apache.org/msg09973.html
- **What it does:** XML-based workflow scheduler for Hadoop jobs (MapReduce, Pig, Hive, Sqoop, SSH). Hadoop's native scheduler. https://oozie.apache.org/
- **License:** Apache 2.0.
- **Architecture:** Java web app in a servlet container. Required a Hadoop cluster (YARN-centric). Database-backed.
- **Workflow format:** XML DAGs (hPDL).
- **Commercial managed tier:** Was bundled with Hadoop distributions (Cloudera, Hortonworks). Effectively dead now.
- **Community health:** Dead. Committers voted to retire due to inactivity.
- **Fit for single-dev local-offline:** No. Retired and Hadoop-only.

### 6. Apache Aurora — RETIRED (~2020)

- **Status:** Retired (~2020, in Attic). https://www.mail-archive.com/announce@apache.org/msg06451.html
- **What it does:** Mesos framework for long-running services, cron jobs, and ad-hoc jobs. Cron was a first-class feature with BSD crontab syntax. https://aurora.apache.org/documentation/latest/features/cron-jobs/
- **License:** Apache 2.0.
- **Architecture:** Required an Apache Mesos cluster. Distributed by definition.
- **Workflow format:** Python-based job definitions (.aurora files).
- **Commercial managed tier:** Was used at Twitter/Salesforce. None now.
- **Community health:** Dead.
- **Fit for single-dev local-offline:** No. Retired and Mesos-only.

### 7. Apache YuniKorn — TLP, active (resource scheduler, NOT job scheduler)

- **Status:** Top-Level Project (graduated 2022). https://yunikorn.apache.org/
- **What it does:** Standalone resource scheduler for K8s/YARN — fine-grained resource sharing, queue hierarchies, gang scheduling, preemption. Replacement for the Kubernetes default scheduler, not a job/cron scheduler. https://yunikorn.apache.org/docs/design/architecture/
- **License:** Apache 2.0.
- **Architecture:** Go. Custom K8s scheduler via a shim. Distributed (runs alongside K8s).
- **Workflow format:** N/A — you submit pods/jobs, YuniKorn decides placement.
- **Commercial managed tier:** None widely known. Community-driven.
- **Community health:** Active, modest.
- **Fit for single-dev local-offline:** No. Wrong category entirely — schedules containers onto nodes, not jobs in time. Only relevant if you run a K8s cluster.

### 8. Apache Airavata — TLP, niche (HPC gateway)

- **Status:** Top-Level Project (still active but low-velocity). https://airavata.apache.org/
- **What it does:** Framework for executing/managing computational jobs on distributed HPC resources — supercomputers, national grids, academic/commercial clouds. Science-gateway middleware. Uses Apache Helix as its workflow engine. https://docs.airavata.org/en/master/technical-documentation/helix-job-management/
- **License:** Apache 2.0.
- **Architecture:** Java, multi-database (profile_service, experiment_catalog, app_catalog, credential_store, etc.). Heavy.
- **Workflow format:** Defined via the gateway portal / API (not YAML/code-first for end users).
- **Commercial managed tier:** None.
- **Community health:** Low velocity, niche academic use.
- **Fit for single-dev local-offline:** No. HPC gateway software — wrong domain.

### 9. Apache Helix — TLP, framework (not a product)

- **Status:** Top-Level Project (originated at LinkedIn). https://helix.apache.org/
- **What it does:** Cluster management framework with a Task Framework for distributed execution of workflows/jobs/tasks. Supports one-time and recurring (cron-scheduled) workflows via YAML or code. https://helix.apache.org/0.9.9-docs/tutorial_task_framework.html
- **License:** Apache 2.0.
- **Architecture:** Java. Requires a Helix cluster (controller + participants) backed by ZooKeeper. Distributed.
- **Workflow format:** Code (Java) OR YAML. DAG of jobs.
- **Commercial managed tier:** LinkedIn internal use primarily.
- **Community health:** Low-to-moderate; library/framework, not a product.
- **Fit for single-dev local-offline:** No. It's a library for building distributed systems, not a standalone runner you install.

### 10. Apache Liminal — RETIRED podling (Jul 2024)

- **Status:** Retired podling, July 2024 (never graduated). https://incubator.apache.org/projects/liminal
- **What it does:** End-to-end ML platform to build/train/deploy models, built on top of Airflow + Kubernetes + Spark.
- **License:** Apache 2.0.
- **Architecture:** Python. Wrapped Airflow.
- **Fit:** No. Dead, and was an Airflow wrapper anyway.

## Out-of-scope (mentioned for completeness)

- **Apache Pekko** (https://pekko.apache.org/) — TLP, Akka 2.6.x fork. Actor concurrency framework, not a scheduler. Nothing to do with job scheduling despite the name overlap.
- **Apache Sling Scheduler** (https://sling.apache.org/documentation/bundles/scheduler-service-commons-scheduler.html) — Quartz-based scheduler embedded inside Apache Sling (a CMS/JCR framework). Not a standalone scheduler; OSGi-only. Irrelevant unless you build on Sling.
- **Apache Griffin** — data quality project that uses Quartz internally for its own cron; retired/defunct and not a general scheduler.

## Direct Dagu competitor check

No Apache project competes directly with Dagu. Dagu's defining traits — single binary, YAML DAGs, file-backed (no DBMS), local-first, Web UI, cron-replacement — have no ASF equivalent.

| Trait | Dagu | Closest ASF project | Gap |
|---|---|---|---|
| Single binary | yes | None | All ASF schedulers are multi-process/JVM/cluster |
| No DB | yes | Airflow (SQLite dev only) | All require a real DB in production |
| YAML DAGs | yes | DolphinScheduler (Python SDK + visual) | No YAML-first ASF scheduler |
| Cron-replacement | yes | Aurora (dead) | No living ASF lightweight cron replacement |
| File-backed state | yes | None | All persist to DB/ZK |

**Conclusion:** The "lightweight, YAML, file-backed, single-binary" niche is entirely unoccupied by the ASF. Dagu (and similar non-Apache tools like Cronicle, Ofelia, DDS) have no Apache rival. The ASF's scheduler projects are uniformly enterprise-scale and DB-dependent.

## Fit summary for single-developer local-offline platform

| Project | Fit | Why |
|---|---|---|
| Airflow | Marginal | Can run standalone w/ SQLite, but heavyweight |
| DolphinScheduler | Poor | JVM + DB + ZK; cluster-oriented |
| NiFi | Wrong tool | Data flow, not job scheduling |
| SeaTunnel | Wrong tool | Data integration, needs external scheduler |
| Oozie | No | Retired, Hadoop-only |
| Aurora | No | Retired, Mesos-only |
| YuniKorn | No | Resource scheduler, not job scheduler |
| Airavata | No | HPC gateway |
| Helix | No | Framework library, not a product |
| Liminal | No | Retired, Airflow wrapper |

**Bottom line:** None of the ASF projects are a good fit for a single-developer, local-offline, single-binary platform. The ASF has no lightweight cron-replacement or Dagu-class tool. If you want an Apache-licensed scheduler in that class, look outside the ASF (Dagu itself, Cronicle, Ofelia, kala, rundeck — none Apache). The ASF's contribution to this space is exclusively enterprise-scale orchestration engines.