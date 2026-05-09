# SDLC Setup

The user will specify a role: `scanner`, `triager`, or `coder`.

## Steps

1. Check if the shared mount exists by running: `ls /workspace/shared/quay-sdlc/`
   If the path does not exist, tell the user: "The shared mount is not available. Please restart this agent's container so the quay-sdlc shared mount is applied, then run setup again." Stop here.

2. Initialize the shared database (safe to run multiple times):
   `python /workspace/.claude/skills/quay-sdlc/db.py init`

3. Create a schedule based on the role. Use the prompt exactly as written — do not expand, rephrase, or inline workflow details:

   **scanner**:
   - prompt: `use quay-sdlc skill as a scanner`
   - trigger_type: `interval`
   - interval_minutes: 5

   **triager**:
   - prompt: `use quay-sdlc skill as a triager`
   - trigger_type: `interval`
   - interval_minutes: 10
   - full_context: true

   **coder**:
   - prompt: `use quay-sdlc skill as a coder`
   - trigger_type: `interval`
   - interval_minutes: 30
   - full_context: true

4. Confirm to the user: which role was set up, the interval, and that the schedule is now active.
