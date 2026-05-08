#!/usr/bin/env bash
# Credential Guard Hook
# Prevents the agent from leaking secrets in tool outputs, chat responses,
# or file writes. Works by checking against actual secret values loaded
# from /workspace/.secrets, plus known credential regex patterns.
#
# Usage: Create a /workspace/.secrets file with one secret per line.
# Lines starting with # are comments. Empty lines are ignored.
#
# Supports hook events: PreToolUse (Write/Edit/Bash), PostToolUse, Stop
#
# Exit 0 + JSON block  = blocked with reason
# Exit 0 + no output   = allowed
# Exit 2               = blocking error

set -euo pipefail

SECRETS_FILE="/workspace/.secrets"
INPUT=$(cat)

# --- Load actual secret values from the secrets file ---
SECRETS=()
if [[ -f "$SECRETS_FILE" ]]; then
    while IFS= read -r line; do
        line=$(echo "$line" | xargs)
        [[ -z "$line" || "$line" == \#* ]] && continue
        SECRETS+=("$line")
    done < "$SECRETS_FILE"
fi

# If no secrets file exists, only run regex pattern checks
if [[ ${#SECRETS[@]} -eq 0 && ! -f "$SECRETS_FILE" ]]; then
    : # fall through to regex checks
fi

# --- Known credential regex patterns (second layer) ---
PATTERNS=(
    'ghp_[A-Za-z0-9]{36}'
    'ghu_[A-Za-z0-9]{36}'
    'ghs_[A-Za-z0-9]{36}'
    'github_pat_[A-Za-z0-9_]{82}'
    'sk-[A-Za-z0-9]{20,}'
    'AKIA[A-Z0-9]{16}'
    'xoxb-[0-9]+-[A-Za-z0-9]+'
    'xoxp-[0-9]+-[A-Za-z0-9]+'
)

block() {
    echo "{\"decision\": \"block\", \"reason\": \"SECURITY: $1\"}"
    exit 0
}

# --- Determine what text to scan based on hook event ---
EVENT=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('hook_event_name',''))" 2>/dev/null || echo "")
TOOL=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null || echo "")

SCAN_TEXT=""
case "$EVENT" in
    PostToolUse)
        SCAN_TEXT=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(json.dumps(d.get('tool_output', '')))" 2>/dev/null || echo "")
        ;;
    PreToolUse)
        case "$TOOL" in
            Bash)
                # Allow: commands that legitimately need the secret (e.g. auth login)
                # Block: any other bash command containing a secret value
                # Add patterns to ALLOWED_PATTERNS as needed for your use case
                COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('command', ''))" 2>/dev/null || echo "")
                ALLOWED_PATTERNS=(
                    'gh auth login'
                    'gh auth setup-git'
                )
                for secret in "${SECRETS[@]}"; do
                    if echo "$COMMAND" | grep -qF "$secret"; then
                        ALLOWED=false
                        for allowed in "${ALLOWED_PATTERNS[@]}"; do
                            if echo "$COMMAND" | grep -qF "$allowed"; then
                                ALLOWED=true
                                break
                            fi
                        done
                        if [[ "$ALLOWED" == "false" ]]; then
                            block "Secret used in unauthorized command. Allowed commands: ${ALLOWED_PATTERNS[*]}"
                        fi
                    fi
                done
                exit 0
                ;;
            Write)
                SCAN_TEXT=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('content', ''))" 2>/dev/null || echo "")
                ;;
            Edit)
                SCAN_TEXT=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('new_string', ''))" 2>/dev/null || echo "")
                ;;
            *)
                exit 0
                ;;
        esac
        ;;
    Stop)
        SCAN_TEXT=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('assistant_message', ''))" 2>/dev/null || echo "")
        ;;
    *)
        exit 0
        ;;
esac

[[ -z "$SCAN_TEXT" ]] && exit 0

# --- Check for exact secret values ---
for secret in "${SECRETS[@]}"; do
    if echo "$SCAN_TEXT" | grep -qF "$secret"; then
        block "Credential value detected in output. The agent attempted to expose a stored secret."
    fi
done

# --- Check for known credential patterns ---
for pattern in "${PATTERNS[@]}"; do
    if echo "$SCAN_TEXT" | grep -qE "$pattern"; then
        block "Credential pattern matched ($pattern). Possible accidental leak."
    fi
done

exit 0
