#!/usr/bin/env bash
set -euo pipefail
for file in "$@"; do
  yq -o=json '.' "$file" | jq -e '
    .name | type == "string"' >/dev/null
  yq -o=json '.' "$file" | jq -e '
    all((.inputs // {})[];
      type == "object" and (.description | type == "string") and
      (keys - ["description","required","default","deprecationMessage"] | length == 0)) and
    all((.outputs // {})[];
      keys == ["description","value"] and (.description | type == "string") and (.value | type == "string")) and
    .runs.using == "composite" and (.runs.steps | type == "array" and length > 0) and
    all(.runs.steps[];
      (has("uses") and (has("run") | not)) or
      (has("run") and .shell == "bash" and (has("uses") | not)))' >/dev/null
done
echo 'Composite action input/output metadata verified.'
