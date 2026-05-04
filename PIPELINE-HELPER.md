# Pipeline Skill Helper

How to create a pipeline skill for takopod's multi-agent workflow engine.

A pipeline skill coordinates specialized agents through sequential phases to complete structured work (bug fixes, feature implementation, triage, etc). Each pipeline skill is a directory containing a project profile, agent role definitions, and one or more workflow definitions.

## Required Files

Every pipeline skill directory must contain:

1. **`SKILL.md`** -- LLM-facing instructions (when to offer the pipeline, how to trigger it)
2. **`profile.yaml`** -- project metadata for template variable resolution
3. **`agents/` directory** -- at least one `.md` file per agent role
4. **One or more workflow `.md` files** -- pipeline definitions (e.g. `bugfix.md`, `feature.md`)

The engine raises `PipelineLoadError` if `profile.yaml`, `agents/`, or a requested workflow file is missing.

## Directory Layout

```
my-pipeline/
  SKILL.md
  profile.yaml
  bugfix.md
  feature.md
  agents/
    dev.md
    tester.md
```

Files named `README.md` and `SKILL.md` are excluded from workflow discovery.

## Installing a Pipeline Skill

There are three ways to install a pipeline skill.

### Option 1: ZIP Upload (recommended)

Package the skill directory as a ZIP and upload via API or UI.

```bash
cd my-pipeline
zip -r ../my-pipeline.zip .
curl -F "file=@my-pipeline.zip" http://localhost:8000/api/skills/upload
```

Or upload through the UI at the System Skills page.

**ZIP constraints:**

- 5 MB uncompressed max, 100 files max
- No symlinks, no absolute paths, no path traversal
- Must contain `SKILL.md` at the root (after stripping a single top-level directory if present)
- `SKILL.md` frontmatter must have a `name` field matching `^[a-z][a-z0-9-]*$` (lowercase, digits, hyphens, starts with letter, max 64 chars)

The upload extracts to `data/skills/<name>/`, adds the skill to all agents' `agent_skills` table, and syncs it to each agent's workspace at `.claude/skills/<name>/`.

### Option 2: API Create

Create the skill entry via API, then upload supporting files separately.

```bash
# Create the skill with SKILL.md content
curl -X POST http://localhost:8000/api/skills \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-pipeline",
    "description": "Multi-agent pipeline for my project",
    "content": "---\nname: my-pipeline\ndescription: ...\n---\n\n# Instructions"
  }'
```

This only creates `SKILL.md`. For pipeline skills you still need `profile.yaml` and `agents/` -- use ZIP upload instead, or place files manually in `data/skills/my-pipeline/`.

### Option 3: Manual Placement

Place the directory directly in `data/skills/` (user-created, mutable) or `skills/` (builtin, git-tracked). Then add it to agents via API or UI:

```bash
curl -X POST http://localhost:8000/api/agents/{agent_id}/registry-skills/my-pipeline
```

After any method, the skill is synced to the agent's workspace at `{workspace}/.claude/skills/my-pipeline/`. The worker must be restarted for changes to take effect.

## File Reference

### SKILL.md

Tells the primary agent when to offer the pipeline and how to trigger it. Not processed by the pipeline engine itself -- it's loaded as a skill prompt.

**Frontmatter:**

- `name` (string, **required**) -- skill identifier, must match `^[a-z][a-z0-9-]*$`
- `description` (string) -- one-line description
- `always_enabled` (bool, default `false`) -- if true, auto-enabled for all agents

**Body:** Markdown instructions covering available workflows, when to offer each one, and how to call `trigger_pipeline(project, workflow, run_id)`.

```markdown
---
name: my-pipeline
description: "Trigger multi-agent pipelines for MyApp"
---

# MyApp Pipeline

## Available Workflows

- **bugfix**: Fix bugs -- investigation through PR creation
- **feature**: Implement features -- spec through PR creation

## When to Offer

- User mentions fixing a bug with an APP ticket -> offer bugfix
- User asks to implement a feature -> offer feature

## How to Trigger

1. Confirm intent: which workflow and ticket
2. Call: `trigger_pipeline(project="my-pipeline", workflow="bugfix", run_id="APP-1234")`
3. Report the result
```

### profile.yaml

Project-level metadata available in templates as `{profile.<key>}`.

**Required fields:**

- `name` (string) -- project name
- `description` (string) -- short project description

**Common optional fields:** `repo`, `stack`, `conventions_file`, `docs_dir`, `commands`, `pr`, `key_directories`. Extra fields are allowed -- the schema uses `ConfigDict(extra="allow")`.

```yaml
name: myapp
description: Internal dashboard application
repo: myorg/myapp
stack: "Python 3.12, FastAPI, React"

commands:
  test_all: "make test"
  lint: "ruff check ."
  typecheck: "mypy src/"

pr:
  title_pattern: "^(APP-\\d+|NO-ISSUE): .+$"
  branch_format: "<type>/<ticket-key>-<short-description>"
  upstream_repo: myorg/myapp

key_directories:
  api: src/api/
  models: src/models/
  tests: tests/
```

### Agent Definitions (agents/*.md)

Each `.md` file in `agents/` defines a specialized agent role. The filename (without `.md`) is the agent name referenced in workflow phases.

**Frontmatter fields:**

- `description` (string, **required**) -- role description
- `model` (string, default `"sonnet"`) -- Claude model
- `maxTurns` (int, default `25`) -- max conversation turns
- `tools` (list of strings, default `null` = all tools) -- allowed tools
- `permissionMode` (string, default `"acceptEdits"`) -- `"acceptEdits"` or `"viewOnly"`

The markdown body becomes the agent's `prompt`. It supports template variables.

```markdown
---
description: "Developer -- implements code changes, runs tests, creates PRs"
model: claude-opus-4-6
maxTurns: 40
tools: [Read, Edit, Write, Bash, Grep, Glob]
permissionMode: acceptEdits
---

You are the Developer for {profile.name} ({profile.description}).

## Your Role

Implement code changes based on the design document.

## Process

1. Read the design at {artifacts_dir}/design.md
2. Implement changes
3. Run tests: `{profile.commands.test_all}`
4. Run lint: `{profile.commands.lint}`

## Output

Write results to {artifacts_dir}/implementation.md.

## Return to Orchestrator

Return a SHORT status (under 200 words):
- Overall result: PASS/FAIL/COMPLETE
- What you did (1-2 sentences)
- Key output file paths
- If FAIL: the specific blocker
```

**Return protocol:** Agents write detailed output to artifact files and return only a short summary (under 200 words) to the orchestrator. This keeps context bounded during rework loops.

### Workflow Files (*.md)

Each workflow file defines a pipeline: the sequence of phases, which agents run, and how artifacts flow between them. The filename (without `.md`) is the workflow name passed to `trigger_pipeline`.

**Format:** YAML frontmatter + markdown prose (orchestrator system prompt).

**Frontmatter fields:**

- `name` (string, **required**) -- must match the filename
- `description` (string, **required**) -- human-readable description
- `version` (int, default `1`)
- `agents` (**required**)
  - `required` (list of strings) -- must exist in `agents/`
  - `optional` (list of strings, default `[]`) -- may be skipped conditionally
- `phases` (list, **required**) -- ordered phase sequence
- `artifacts` (**required**)
  - `directory` (string) -- supports `{run_id}` template
  - `status_file` (string, default `"status.json"`)
- `orchestrator` (optional)
  - `model` (string, default `"sonnet"`)
  - `max_turns` (int, default `100`)
  - `effort` (string, default `"high"`)

**Phase fields:**

- `name` (string, **required**) -- unique identifier
- `output` (string, **required**) -- artifact filename this phase produces
- `agent` (string or null, default null) -- which agent runs it; null = orchestrator handles it
- `condition` (string, default null) -- conditional execution (e.g. `"complexity == complex"`)
- `input` (list of strings, default `[]`) -- artifacts from earlier phases
- `description` (string) -- human-readable description
- `rework` (optional) -- rework loop config
  - `agent` (string, **required**) -- agent that handles rework
  - `max` (int, **required**, >= 1) -- max iterations
  - `when` (`"fail"` or `"rework"`) -- trigger condition

**Validation rules enforced by the loader:**

- All `agents.required` and `agents.optional` entries must have `.md` files in `agents/`
- All `agent` and `rework.agent` values in phases must reference defined agents
- Phase `input` artifacts must be produced by an earlier phase's `output`
- No two phases can share the same `output` value

#### Minimal Workflow Example

```yaml
---
name: simple
description: Simple single-agent task
version: 1

agents:
  required: [dev]
  optional: []

phases:
  - name: implement
    agent: dev
    output: implementation.md
    description: "Implement the task"

artifacts:
  directory: ".pipeline/{run_id}"
---

# Task Orchestrator

You coordinate the dev agent for {profile.name}.

## Setup

```bash
mkdir -p {artifacts_dir}
```

## Execution

Dispatch the **dev** agent:
> Implement the task for {run_id}. Write results to {artifacts_dir}/implementation.md.

Read {artifacts_dir}/implementation.md and report the result.
```

#### Multi-Phase Workflow Example

```yaml
---
name: bugfix
description: Fix bugs with investigation, implementation, and testing
version: 1

agents:
  required: [dev, tester]
  optional: [reviewer]

phases:
  - name: investigate
    agent: dev
    output: design.md

  - name: review
    agent: reviewer
    condition: "complexity == complex"
    input: [design.md]
    output: review.md
    rework:
      agent: dev
      max: 2
      when: rework

  - name: implement
    agent: dev
    input: [design.md]
    output: implementation.md

  - name: test
    agent: tester
    input: [design.md, implementation.md]
    output: test-results.md
    rework:
      agent: dev
      max: 3
      when: fail

artifacts:
  directory: ".pipeline/{run_id}"
  status_file: status.json

orchestrator:
  model: claude-opus-4-6
  max_turns: 100
  effort: high
---

# Bug Fix Orchestrator

You coordinate agents to fix bugs for {profile.name}.
...
```

## Template Variables

All workflow prose and agent prompts support template resolution.

**Available variables:**

- `{profile.<key>}` -- any value from profile.yaml (dot-notation for nesting: `{profile.commands.test_all}`)
- `{artifacts_dir}` -- resolved artifact directory (e.g. `.pipeline/APP-1234`)
- `{run_id}` -- pipeline run ID passed at trigger time
- `{{` / `}}` -- literal braces (use in JSON templates within prompts)

## Triggering a Pipeline

Pipelines are triggered via the `trigger_pipeline` MCP tool:

- `project` (string) -- skill directory name (e.g. `"my-pipeline"`)
- `workflow` (string) -- workflow name matching a `.md` file (e.g. `"bugfix"`)
- `run_id` (string) -- run identifier (e.g. a JIRA ticket key `"APP-1234"`)

The orchestrator loads the config, validates it, resolves templates, builds a phase summary table, and queues a pipeline message. The pipeline then runs autonomously.

## Execution Lifecycle

1. Primary agent calls `trigger_pipeline(project, workflow, run_id)`
2. Orchestrator loads `profile.yaml`, `agents/*.md`, `<workflow>.md`
3. Validates structural integrity (agent refs, phase DAG)
4. Resolves `{profile.*}`, `{artifacts_dir}`, `{run_id}` templates
5. Appends a phase summary table to the orchestrator prompt
6. Queues a pipeline message with the resolved payload
7. Worker spawns orchestrator agent with system prompt + agent definitions
8. Orchestrator dispatches subagents phase-by-phase, passing artifacts between them
9. Progress tracked in `{artifacts_dir}/status.json` and agent memory

## Writing the Orchestrator Prompt

The workflow prose (markdown body after frontmatter) serves as the orchestrator's system prompt. It should cover:

- **Pipeline run rules** -- autonomous execution, no user interaction
- **Context passing** -- search memory before dispatching agents
- **Artifact protocol** -- read artifact files, not agent return messages
- **Session resumption** -- check memory for prior progress, skip completed phases
- **Setup** -- create artifact directory, initialize status.json, store initial state in memory
- **Phase dispatch instructions** -- what to tell each agent, what to pass as context
- **Conditional routing** -- how to handle different complexity levels or conditions
- **Rework loops** -- what to do when agents return FAIL or REWORK
- **Error handling** -- max retries, failure reporting, memory storage on failure
- **Progress tracking** -- update status.json and memory after each phase
- **Completion** -- write summary, store final state, report result

Use `{{` and `}}` for literal JSON braces within the prompt:

```
Write status.json:
{{
  "run_id": "{run_id}",
  "pipeline": "bugfix",
  "current_phase": "triage"
}}
```

## Checklist

- [ ] `SKILL.md` has `name` field in frontmatter matching `^[a-z][a-z0-9-]*$`
- [ ] `profile.yaml` has `name` and `description`
- [ ] `agents/` directory has at least one `.md` file
- [ ] Each agent `.md` has `description` in frontmatter and a markdown prompt body
- [ ] At least one workflow `.md` file (not `README.md` or `SKILL.md`)
- [ ] Workflow frontmatter has `name`, `description`, `agents`, `phases`, `artifacts`
- [ ] All agents referenced in `phases` and `rework` exist in `agents/`
- [ ] Phase `input` artifacts are produced by earlier phase `output` values
- [ ] No duplicate `output` values across phases
- [ ] Agent prompts end with a "Return to Orchestrator" section (short summary protocol)
- [ ] Workflow prose includes setup, dispatch, error handling, and completion sections
- [ ] ZIP passes validation: under 5 MB, under 100 files, no symlinks
