#!/usr/bin/env bash
# Existing bootstrap regressions migrated with the owner from Python to Shell.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PRIVATE=$(mktemp -d)
trap 'rm -rf -- "$PRIVATE"' EXIT
bash -n "$ROOT/scripts/bootstrap_prod_selfhost.sh"
bash "$ROOT/scripts/bootstrap_prod_selfhost.sh" --help >/dev/null
JQ=(jq -e -L "$ROOT/scripts/lib")
jq -n -L "$ROOT/scripts/lib" 'include "prod-bootstrap";
  {resource_changes:[targets("identity")[] | . as $address |
    {address:$address,mode:"managed",type:(if contains("iam_member") then "google_project_iam_member" else "google_project_service" end),
    change:{actions:["create"],before:null,after_unknown:{id:true},after:(
      if contains("iam_member") then {project:project,role:(split("\"")[1]),member:member,condition:[]}
      else {project:project,service:"orgpolicy.googleapis.com",disable_on_destroy:false} end)}}]}' >"$PRIVATE/identity.json"
jq -n -L "$ROOT/scripts/lib" 'include "prod-bootstrap";
  {resource_changes:[{address:targets("external-ip")[0],mode:"managed",type:"google_org_policy_policy",
    change:{actions:["create"],before:null,after_unknown:{spec:[{etag:true,update_time:true}]},after:{
      name:"projects/986070475391/policies/compute.vmExternalIpAccess",parent:"projects/open-platform-prod",
      spec:[{rules:[{allow_all:null,deny_all:null,condition:[],values:[{allowed_values:[instance],denied_values:null}]}]}]}}}]}' >"$PRIVATE/policy.json"
accept() { "${JQ[@]}" --arg stage "$2" 'include "prod-bootstrap"; plan_targets($stage)' "$1" >/dev/null; }
reject() {
  local file=$1 stage=$2 transform=$3
  jq "$transform" "$file" >"$PRIVATE/bad.json"
  if accept "$PRIVATE/bad.json" "$stage" 2>/dev/null; then echo "unsafe plan accepted: $transform" >&2; exit 1; fi
}
accept "$PRIVATE/identity.json" identity
accept "$PRIVATE/policy.json" external-ip
for action in '["delete"]' '["delete","create"]' '["create","delete"]' '[]'; do
  reject "$PRIVATE/identity.json" identity ".resource_changes[0].change.actions=$action"
done
reject "$PRIVATE/identity.json" identity '.resource_changes[0].address="google_service_account.github_actions"'
reject "$PRIVATE/identity.json" identity '.resource_changes=[]'
reject "$PRIVATE/identity.json" identity '.resource_changes += [.resource_changes[0]]'
reject "$PRIVATE/identity.json" identity '.resource_changes[0].change.after.role="roles/orgpolicy.policyAdmin"'
reject "$PRIVATE/identity.json" identity '.resource_changes[0].change.after.member="serviceAccount:other@example.com"'
reject "$PRIVATE/identity.json" identity '.resource_changes[0].change.after.project="open-platform-uat"'
reject "$PRIVATE/identity.json" identity '.resource_changes[0].change.after_unknown.member=true'
reject "$PRIVATE/policy.json" external-ip '.resource_changes[0].change.after.spec[0].rules[0].allow_all="TRUE"'
reject "$PRIVATE/policy.json" external-ip '.resource_changes[0].change.after.spec[0].rules[0].condition=[{expression:"true"}]'
reject "$PRIVATE/policy.json" external-ip '.resource_changes[0].change.after.spec[0].inherit_from_parent=true'
reject "$PRIVATE/policy.json" external-ip '.resource_changes[0].change.after.name="projects/986070475391/policies/other"'
reject "$PRIVATE/policy.json" external-ip '.resource_changes[0].change.before=.resource_changes[0].change.after | .resource_changes[0].change.before.spec[0].rules[0].values[0].allowed_values += ["other"]'
reject "$PRIVATE/policy.json" external-ip '.resource_changes[0].change.after_unknown.spec[0].rules[0].values=[{allowed_values:true}]'
reject "$PRIVATE/identity.json" identity '.errored=true'
reject "$PRIVATE/identity.json" identity '.deferred_changes=[{}]'
jq -n '{lineage:"existing",serial:1,resources:[
  {mode:"managed",type:"google_service_account",name:"github_actions",instances:[]},
  {mode:"managed",type:"google_iam_workload_identity_pool",name:"github",instances:[]},
  {mode:"managed",type:"google_iam_workload_identity_pool_provider",name:"github",instances:[]}]}' >"$PRIVATE/state.json"
"${JQ[@]}" 'include "prod-bootstrap"; state_snapshot("identity")' "$PRIVATE/state.json" >/dev/null
jq '.resources=[]' "$PRIVATE/state.json" >"$PRIVATE/bad.json"
if "${JQ[@]}" 'include "prod-bootstrap"; state_snapshot("identity")' "$PRIVATE/bad.json" >/dev/null 2>&1; then exit 1; fi
echo 'Shell bootstrap guards preserve bounded targets and protected state.'
