# Scanner Workflow

Scan Jira for tickets labeled `shossain` and record new ones in the shared DB. Do NOT triage or comment.

## Steps

1. Search Jira: `jira_search(jql='labels = "shossain" ORDER BY created DESC', fields='summary,status,priority,issuetype,url')`.
2. For each result, run:
   `python /workspace/.claude/skills/quay-sdlc/db.py add <TICKET_KEY> --summary "<summary>" --priority "<priority>" --issue-type "<issuetype>" --url "<url>"`
   Duplicates are silently skipped. Do not pre-check the DB.
