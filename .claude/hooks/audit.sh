#!/usr/bin/env bash
set -uo pipefail

input=$(cat)
tool=$(jq -r '.tool_name // "?"' <<<"$input")
detail=$(jq -r '.tool_input.command // .tool_input.file_path // "-"' <<<"$input" | tr '\n' ' ')

printf '%s\t%s\t%s\n' \
  "$(date -Is)" \
  "$tool" \
  "$detail" >> "${CLAUDE_PROJECT_DIR}/.claude/audit.log"

exit 0
