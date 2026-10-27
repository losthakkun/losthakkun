## ❯ `whoami`

```txt
Asarel Alejandro Núñez Segoviano
Lead Software Engineer · Product Engineering
WEPORT (Radiant Logistics) · Mexico City · Spanish / English


  human          need ─▶ discovery ─▶ specs ────────▶ decisions ─────────────▶ merge ─▶ measure
                                        │                 ▲                        ▲
  orchestrator                        tasks ─▶ route ─▶ verdict / S# ─▶ review ─▶ commit
                                                 │                ▲       │          ▲
  agents                                      explore ─▶ build ─▶ verify  └ 4 lenses ┘
                                                         red → green · fresh context · refuter

  memory         ◀─────── decisions, verdicts and failures, recalled by the next session ───────▶
```

Ten years shipping software end to end: web, mobile, backend and cloud, from the first
conversation about a need through to a number that shows the outcome moved. Product engineering
by scope rather than by title: I decide what gets built and on which stack, then carry it
through discovery, build, deploy and adoption.

Agentic development is what widened that scope, and it's where most of my attention goes now.
I own the specs and the review, agents work inside them under test-first contracts, and a
change isn't done until there's evidence it moved something. The practice goes past the
codebase: IT infrastructure, security and governance, and helping teams outside engineering
pick up AI and automation.

The depth underneath comes from cross-platform work: React and React Native products on iOS,
Android and AndroidTV hardware, with the native modules, backend and cloud behind them.

## ◆ `current_scope`

```txt
+ Owning initiatives end to end: discovery, MVP scope, build, deploy, adoption
+ Choosing the stack per project against technical and commercial constraints
+ Shipping cross-platform products on React and React Native, web to mobile to TV
+ Designing agentic workflows governed by TDD, ODD and adversarial review
+ Building the harnessing layer that keeps agent context governed and reproducible
+ Tuning AI economics, measuring token cost against delivered capacity
+ Improving IT infrastructure alongside product: security, governance, centralization
+ Bringing other areas and stakeholders onto AI and automation
+ Driving adoption from C-level to operators, new hires and vendors
```

## ◇ `track`

```txt
2025 · now    WEPORT / Radiant Logistics    Lead Software Engineer · freight forwarding
2023 · 2025   VOXPOP                        Software Development Manager · retail streaming
2016 · 2022   VOXPOP                        Full-stack · AndroidTV, React Native, AWS
2018 · now    Independent                   React / React Native cross-platform products ·
                                            agentic workflows for operations and dev teams

Native modules, device fleets, streaming platforms, hardware, IT operations. Infrastructure
is still part of the job. Most of what I know about how systems fail, I learned there.
```

## ≡ `stack`

Fundamentals are the part that carries over. Data structures, concurrency, protocols, how a
system behaves under load. They hold across every language on this list, and they're what let
me spot a wrong answer from an agent.

Memorizing a framework's surface stopped being the hard part. The hard part now is picking the
stack that fits a problem on technical and commercial grounds, then getting an organization to
move to it. What follows is what the work runs on today. I've gone deeper in some of it than
in the rest.

```txt
Foundations    Data structures, concurrency, protocols, system design, debugging from
               first principles
Judgment       Stack selection against technical and commercial constraints, MVP scoping,
               trade-off calls under ambiguity, adoption and enablement
Organization   IT infrastructure, security and governance, process centralization,
               cross-area AI and automation adoption
Orchestration  Claude Code, opencode, MCP servers, subagent routing, multi-agent
               adversarial review, in-house harnessing layer (devsource)
Method         TDD, Red-Green-Refactor, ODD (Organic Driven Development), contracts first
Intelligence   GitNexus cross-repo graph, CodeGraph per-repo index, Engram team memory
               shared across agents and sessions
Languages      TypeScript, JavaScript, Node.js, Python, PHP, Bash
Interfaces     React, Vite, Next.js, Tailwind, React Native with native modules (Android / iOS),
               Native Bridge and Fabric
Services       FastAPI, Flask, Pydantic, Express, Laravel
Data           PostgreSQL, MySQL, DynamoDB, Athena, medallion data lakes
Cloud          AWS Lambda / S3 / DynamoDB / Athena / IAM, Serverless, Docker, GitHub Actions
Quality        Vitest, Jest, Playwright, DORA metrics, chaos testing, data-quality reporting
Domain         Freight forwarding, retail streaming, internal platforms, integrations
```

## § `engineering_principles`

```txt
1. Prefer clear boundaries over clever abstractions.
2. Treat APIs and integrations as contracts.
3. An agent is only as reliable as its context. Govern the inputs, review the outputs.
4. Know the fundamentals well enough to tell when the agent is wrong.
5. Adopt on evidence, not on novelty. Measure the cost before committing to the tool.
6. Automate the boring parts, keep the important parts explicit.
```

## ∿ `signals`

Generated daily from WakaTime and the GitHub API, so nothing here is typed in by hand. That
also limits them to what those APIs can see. When a metric needs a caveat to be true, I leave
it out.

<!--START_SECTION:agent-impact-->
```txt
agent_workflow — last 7 days
  no activity tracked

delivery — last 30 days
  prs_opened     557
  prs_merged     472 (85% of opened)
  pr_size        median 319 lines per merged PR
  lines_shipped  +300,047 / -45,816
  active_repos   16
  reviews_given  1
  contributions  1,631 (private included)
  active_days    25 of 30 days
  streak         12 consecutive days

commit_rhythm — last 30 days · America/Mexico_City
  morning  06-12  335 commits  🟦🟦🟦🟦🟦🟦⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛  27.8%
  daytime  12-18  591 commits  🟦🟦🟦🟦🟦🟦🟦🟦🟦🟦⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛  49.1%
  evening  18-24  259 commits  🟦🟦🟦🟦⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛  21.5%
  night    00-06   18 commits  ⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛   1.5%

pace — since 2019-05-24
  tracked_total  2364h 45m across 7.4 years
  last_30_days   65h 04m (15h 11m per week)
```

_Updated 2026-10-26 11:38 UTC_
<!--END_SECTION:agent-impact-->

## ↻ `where_the_time_goes`

<!--START_SECTION:waka-->

 Last Updated on 27/10/2026 11:07:56 UTC
<!--END_SECTION:waka-->

## ∎ `thesis`

The split between developer, product manager and QA is dissolving. The product engineer becomes
the base unit: one person carries a business need from discovery through to a measured outcome,
with agents doing the mechanical work inside contracts a human owns. Teams get smaller and
their scope gets wider.

This changes the job itself. Getting a model to write code turned out to be the easy part. The
work is in making that leverage trustworthy: context you govern, output you can audit, data the
organization can decide with, and a number at the end that shows whether any of it mattered.

It moved what depth means, too. Fundamentals still decide outcomes, because they're how you
catch a wrong answer. Framework trivia doesn't, because that's the part the agent covers. The
scarce skills are reading a business need, picking a stack that fits it commercially as well as
technically, and getting people to adopt the change. Language choice is an implementation
detail now.

What I'm working toward is turning this into a discipline. Standards, guardrails, enablement,
so the practice survives being handed to someone else. Right now it's mostly folklore, passed
between people who happened to figure it out.

Two things I don't buy. **Autonomy without governance:** broad access with no contracts,
acceptance criteria or audit trail gives you speed you can't trace. And **metrics theater:**
I removed a lead-time metric from this page because the number was accurate and measured
nothing.

<!--
losthakkun/losthakkun is a special repository because its README.md
appears on the GitHub profile.
-->
