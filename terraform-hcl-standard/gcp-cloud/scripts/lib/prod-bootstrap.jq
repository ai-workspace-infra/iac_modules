# Pure data guards used by the Shell owner. No provider execution here.
def ensure($ok; $message): if $ok then . else error($message) end;
def project: "open-platform-prod";
def member: "serviceAccount:github-actions-prod@open-platform-prod.iam.gserviceaccount.com";
def instance: "projects/open-platform-prod/zones/asia-east1-a/instances/web-saas-prod";
def targets($stage): if $stage == "identity" then
  ["google_project_iam_member.deploy[\"roles/compute.securityAdmin\"]",
   "google_project_iam_member.deploy[\"roles/orgpolicy.policyViewer\"]",
   "google_project_service.platform[\"orgpolicy.googleapis.com\"]"]
  else ["google_org_policy_policy.vm_external_ip_access"] end;
def declarations:
  . as $docs | .oidc as $o | .resource as $r
  | ensure($o.kind == "GitHubActionsOIDCConfig" and $r.kind == "GCPWorkloadNamespace"; "declaration kind mismatch")
  | ensure(all([$o,$r][]; .apiVersion == "gitops.svc.plus/v1alpha1" and
      .metadata.environment == "prod" and .metadata.provider == "gcp" and
      .spec.project_id == project and (.spec.organization_id|tostring) == "744119519286" and
      .spec.gcp_account_id == "xworktech"); "PROD declaration identity mismatch")
  | ensure($o.spec.repository == "ai-workspace-infra/platform-ops-toolkit" and
      $o.spec.service_account_id == "github-actions-prod" and $o.spec.pool_id == "github-actions" and
      $o.spec.provider_id == "github" and
      $o.spec.provider_url == "https://token.actions.githubusercontent.com" and
      $o.spec.audience == "https://iam.googleapis.com/projects/986070475391/locations/global/workloadIdentityPools/github-actions/providers/github" and
      ($o.spec.subjects|sort) == (["repo:ai-workspace-infra/platform-ops-toolkit:environment:prod",
        "repo:ai-workspace-infra/platform-ops-toolkit:ref:refs/heads/main",
        "repo:ai-workspace-infra/platform-ops-toolkit:ref:refs/tags/v*",
        "repo:ai-workspace-infra/platform-ops-toolkit:ref:refs/tags/uat-*"]|sort);
      "WIF identity or subjects mismatch")
  | ensure($o.spec.state.key == "platform-ops-toolkit/prod/xworktech/gcp-oidc-bootstrap/terraform.tfstate" and
      $r.spec.state.key == "terraform/prod/svc.plus/gcp-cloud/xworktech/web-saas/terraform.tfstate";
      "existing state key mismatch")
  | ensure($r.metadata.name == "web-saas" and $r.spec.workspace == "web-saas" and
      $r.spec.state_namespace == "web-saas" and $r.spec.state_project == "svc.plus" and
      ($r.spec|if has("manage_external_ip_policy") then .manage_external_ip_policy == true else true end) and
      $r.spec.external_ip_allowed_instances == [{name:"web-saas-prod",zone:"asia-east1-a"}];
      "resource namespace or policy allowance mismatch");
def permitted_flag: . == null or . == false or . == "FALSE";
def plan_targets($stage):
  ensure(.errored != true and ((.deferred_changes // [])|length) == 0 and
    (.resource_changes|type) == "array"; "invalid or deferred Terraform plan")
  | [ .resource_changes[]
    | . as $item | .change as $c | ($c.after // {}) as $a
    | ensure(([ ["no-op"],["read"],["create"],["update"] ]|any(.[]; . == $c.actions));
        if .address == "google_org_policy_policy.vm_external_ip_access" and
          (($c.replace_paths // [])|any(.[]; . == ["parent"])) then "policy parent replacement rejected"
        elif .address == "google_org_policy_policy.vm_external_ip_access" and
          (($c.replace_paths // [])|any(.[]; . == ["name"])) then "policy name replacement rejected"
        else "delete replace or unknown action rejected" end)
    | if .mode == "data" then
        ensure($stage == "external-ip" and .address == "module.project.data.google_project.existing[0]";
          "unexpected data dependency") | empty
      elif $c.actions == ["no-op"] and ((targets($stage)|index($item.address)) == null) then empty
      else
        ensure(.mode == "managed" and (targets($stage)|index($item.address)) != null;
          "write outside bootstrap targets")
        | ensure(all(["project","role","member","parent","spec"][];
            . as $key | all((($c.after_unknown // {})[$key] |
              if $key == "spec" then walk(if type == "object" then del(.etag,.update_time) else . end) else . end | ..);
              . != true)); "unknown target contract")
        | if $stage == "identity" then
            ensure($a.project == project; "IAM API project mismatch")
            | if .type == "google_project_iam_member" then
                ensure((["roles/compute.securityAdmin","roles/orgpolicy.policyViewer"]|index($a.role)) != null and
                  $a.member == member and .address == ("google_project_iam_member.deploy[\""+$a.role+"\"]") and
                  (($a.condition // [])|length) == 0; "IAM grant mismatch")
              else ensure(.type == "google_project_service" and $a.service == "orgpolicy.googleapis.com" and
                  $a.disable_on_destroy == false; "API enablement mismatch") end
          else
            ensure(.type == "google_org_policy_policy" and
              (["projects/986070475391/policies/compute.vmExternalIpAccess","compute.vmExternalIpAccess"]|index($a.name)) != null and
              $a.parent == "projects/open-platform-prod" and ($a.spec|length) == 1 and
              ($a.spec[0].inherit_from_parent|not) and ($a.spec[0].reset|not) and
              ($a.spec[0].rules|length) == 1; "policy identity or local rule mismatch")
            | $a.spec[0].rules[0] as $rule
            | ensure((($rule.condition // [])|length) == 0 and ($rule.allow_all|permitted_flag) and
                ($rule.deny_all|permitted_flag) and ($rule.values|length) == 1 and
                $rule.values[0].allowed_values == [instance] and
                (($rule.values[0].denied_values // [])|length) == 0; "broad conditional or incorrect policy")
            | ensure(all(($c.before.spec // [])[]; all((.rules // [])[];
                ((.condition // [])|length) == 0 and (.allow_all|permitted_flag) and
                all((.values // [])[]; all((.allowed_values // [])[]; . == instance))));
                "existing policy requires separate review")
          end
        | {address, actions:$c.actions, contract:($a|with_entries(select(.key|IN("project","role","member","service","parent"))))}
          + (if $stage == "external-ip" then {contract:(($a|{parent}) + {allowed_instances:[instance]})} else {} end)
          + {_change:$c}
      end ]
  | ensure((map(.address)|sort) == (targets($stage)|sort); "duplicate or omitted bootstrap target")
  | sort_by(.address);
def state_snapshot($stage):
  ensure((.lineage|type) == "string" and (.lineage|length) > 0 and
    (.serial|type) == "number" and .serial >= 0 and .serial == (.serial|floor);
    "existing state lineage serial required")
  | {lineage,serial,protected:[.resources[] | select(.mode == "managed")
    | select(if $stage == "identity" then (.type|IN("google_service_account","google_iam_workload_identity_pool","google_iam_workload_identity_pool_provider"))
      else (.type|IN("google_compute_network","google_compute_subnetwork","google_compute_disk","google_compute_instance")) end)
    | {address:([.module,.type,.name]|map(select(. != null and . != ""))|join(".")), instances:(.instances // [])}]}
  | . as $snapshot
  | (if $stage == "identity" then ["google_service_account.github_actions","google_iam_workload_identity_pool.github","google_iam_workload_identity_pool_provider.github"]
     else ["module.network.google_compute_network.this","module.network.google_compute_subnetwork.this","module.data_disk_web_saas_prod.google_compute_disk.this"] end) as $required
  | ensure(all($required[]; . as $address | any($snapshot.protected[]; .address == $address));
      "existing protected state missing do not create second state");
