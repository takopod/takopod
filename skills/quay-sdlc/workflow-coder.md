# Coder Workflow

Pick up triaged tickets, implement fixes via sub-agent delegation, create draft PRs.

**IMPORTANT: Process exactly ONE ticket per run. Never loop or batch multiple tickets.**

## Steps

1. Run `python /workspace/.claude/skills/quay-sdlc/db.py list --status triaged --limit 1 --sort priority` to get the highest-priority ticket.
2. If output says "No tickets", stop.
3. For the ticket:
   a. Claim it: `python /workspace/.claude/skills/quay-sdlc/db.py update <TICKET_KEY> assigned`
      If this fails (already claimed), stop.
   b. Get full details: `jira_get_issue(issue_key="<TICKET_KEY>", fields="summary,status,priority,issuetype,assignee,reporter,labels,description,created,updated,url")`
   c. Create artifact directory: `mkdir -p .pipeline/<TICKET_KEY>`
   d. Save JIRA details to `.pipeline/<TICKET_KEY>/jira-ticket.md`
   e. Delegate to sub-agents using the Agent tool, following the appropriate sequence based on issue type:

      **For bugs:**
      1. Delegate to **pse** agent: "Investigate bug <TICKET_KEY>. Read .pipeline/<TICKET_KEY>/jira-ticket.md for the ticket. Write root cause analysis and fix design to .pipeline/<TICKET_KEY>/design.md."
      2. Read .pipeline/<TICKET_KEY>/design.md to verify the design was written.
      3. Delegate to **ssd** agent: "Implement the fix for <TICKET_KEY>. Read .pipeline/<TICKET_KEY>/design.md for the design. Write implementation summary to .pipeline/<TICKET_KEY>/implementation.md."
      4. Read .pipeline/<TICKET_KEY>/implementation.md to verify implementation completed.
      5. Delegate to **qe** agent: "Test the implementation for <TICKET_KEY>. Read .pipeline/<TICKET_KEY>/design.md and .pipeline/<TICKET_KEY>/implementation.md. Write results to .pipeline/<TICKET_KEY>/test-results.md."
      6. Read .pipeline/<TICKET_KEY>/test-results.md. If QE reports FAIL, delegate back to **ssd** to fix, then re-run **qe** (max 2 rework cycles).

      **For features:**
      1. Delegate to **pm** agent: "Write a spec for <TICKET_KEY>. Read .pipeline/<TICKET_KEY>/jira-ticket.md for the ticket. Write spec to .pipeline/<TICKET_KEY>/spec.md."
      2. Delegate to **pse** agent: "Design the implementation for <TICKET_KEY>. Read .pipeline/<TICKET_KEY>/spec.md and .pipeline/<TICKET_KEY>/jira-ticket.md. Write design to .pipeline/<TICKET_KEY>/design.md."
      3. Delegate to **de** agent: "Review the design for <TICKET_KEY>. Read .pipeline/<TICKET_KEY>/design.md and .pipeline/<TICKET_KEY>/spec.md. Write review to .pipeline/<TICKET_KEY>/review.md." If REWORK, send back to **pse** (max 2 rework cycles).
      4. Delegate to **ssd** agent: "Implement <TICKET_KEY>. Read .pipeline/<TICKET_KEY>/design.md for the design. Write implementation summary to .pipeline/<TICKET_KEY>/implementation.md."
      5. Delegate to **qe** agent: "Test the implementation for <TICKET_KEY>. Write results to .pipeline/<TICKET_KEY>/test-results.md."
      6. If QE reports FAIL, delegate back to **ssd** to fix, then re-run **qe** (max 2 rework cycles).

   f. On success (QE passes):
      `python /workspace/.claude/skills/quay-sdlc/db.py update <TICKET_KEY> done --notes "PR: <pr_url>"`
      Then: `jira_add_comment(issue_key="<TICKET_KEY>", body="[takopod] Draft PR created: <pr_url>")`
   g. On failure:
      `python /workspace/.claude/skills/quay-sdlc/db.py update <TICKET_KEY> failed --notes "<what failed>"`
      Then: `jira_add_comment(issue_key="<TICKET_KEY>", body="[takopod] Implementation failed: <reason>")`
