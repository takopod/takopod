# Triager Workflow

Triage new tickets from the shared DB. Delegate investigation to the triage-analyst agent. Comment findings on Jira.

**IMPORTANT: Process exactly ONE ticket per run. Never loop or batch multiple tickets.**

## Steps

1. Run `python /workspace/.claude/skills/quay-sdlc/db.py list --status new --limit 1` to get the next untriaged ticket.
2. If output says "No tickets", stop.
3. For the ticket:
   a. Claim it: `python /workspace/.claude/skills/quay-sdlc/db.py update <TICKET_KEY> triaging`
      If this fails (already claimed), stop.
   b. Get full details: `jira_get_issue(issue_key="<TICKET_KEY>", fields="summary,status,priority,issuetype,assignee,reporter,labels,description,created,updated,url")`
   c. Create artifact directory: `mkdir -p .pipeline/<TICKET_KEY>`
   d. Save the JIRA details to `.pipeline/<TICKET_KEY>/jira-ticket.md`
   e. Delegate triage to the **triage-analyst** agent using the Agent tool:

      > Triage JIRA ticket <TICKET_KEY>.
      > Read the ticket at .pipeline/<TICKET_KEY>/jira-ticket.md.
      > Write your triage report to .pipeline/<TICKET_KEY>/triage-report.md.

   f. Read .pipeline/<TICKET_KEY>/triage-report.md for the full findings.
   g. If triage finds a reproducible bug or actionable feature request:
      `python /workspace/.claude/skills/quay-sdlc/db.py update <TICKET_KEY> triaged --notes "<one-line triage summary>"`
      Then comment on Jira: `jira_add_comment(issue_key="<TICKET_KEY>", body="[takopod triage] <triage findings>")`
   h. If triage finds the issue is a duplicate, not reproducible, or missing information:
      `python /workspace/.claude/skills/quay-sdlc/db.py update <TICKET_KEY> invalid --notes "<reason>"`
      Then comment on Jira: `jira_add_comment(issue_key="<TICKET_KEY>", body="[takopod triage] Invalid: <reason>")`
