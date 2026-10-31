#!/usr/bin/env bash
set -euo pipefail
# IaC owner: migrated from Platform-Orchestrator scripts/cloud/bootstrap/gcp (GCP WIF/OIDC bootstrap declaration resolver).

environment="${GCP_ENVIRONMENT:?GCP_ENVIRONMENT is required}"
config_file="${GCP_OIDC_CONFIG:?GCP_OIDC_CONFIG is required}"
# TODO(Task 5 / gitops#677): hardcoded identity contract still lives here and
# must move to GitOps declarations (GitHubActionsOIDCConfig / provider
# registry) before Task 2 is complete:
#   - expected_repository  ai-workspace-infra/platform-ops-toolkit
#   - expected_organization_id 744119519286
#   - project_by_environment uat/prod/shared -> open-platform-{uat,prod}
#   - shared override open-platform-shared -> open-platform-shared-510113
#   - state key layout platform-ops-toolkit/<env>/<account>/gcp-oidc-bootstrap
#   - custom audience prefix https://github.com/ai-workspace-infra/platform-ops-toolkit/
#   - github_environment mapping shared -> prod
#   - service_account_id convention github-actions-<env>
readonly expected_repository="ai-workspace-infra/platform-ops-toolkit"
readonly expected_organization_id="744119519286"

case "${environment}" in
  uat|prod|shared) ;;
  *) echo "GCP_ENVIRONMENT must be uat, prod, or shared, got: ${environment}" >&2; exit 1 ;;
esac
test -f "${config_file}" || { echo "GCP OIDC declaration not found: ${config_file}" >&2; exit 1; }
command -v ruby >/dev/null 2>&1 || { echo "ruby is required to validate GCP OIDC declaration" >&2; exit 1; }

export GCP_ENVIRONMENT CONFIG_FILE="${config_file}" EXPECTED_REPOSITORY="${expected_repository}" EXPECTED_ORGANIZATION_ID="${expected_organization_id}"
ruby <<'RUBY'
require "yaml"
require "json"

environment = ENV.fetch("GCP_ENVIRONMENT")
config = YAML.load_file(ENV.fetch("CONFIG_FILE"))
spec = config.fetch("spec")
metadata = config.fetch("metadata")
project_by_environment = {
  "uat" => "open-platform-uat",
  "prod" => "open-platform-prod",
  "shared" => "open-platform-prod"
}
expected_project = project_by_environment.fetch(environment)
account_id = spec["gcp_account_id"].to_s
expected_project = "open-platform-shared-510113" if environment == "shared" && account_id == "open-platform-shared"
expected_state_key = if environment == "shared" && account_id == "open-platform-shared"
  "platform-ops-toolkit/shared/#{expected_project}/gcp-oidc-bootstrap/terraform.tfstate"
else
  "platform-ops-toolkit/#{environment}/#{account_id}/gcp-oidc-bootstrap/terraform.tfstate"
end
expected_audience_prefix = "https://iam.googleapis.com/"
custom_audience_prefix = "https://github.com/ai-workspace-infra/platform-ops-toolkit/"
github_environment = environment == "shared" ? "prod" : environment
required_subject = "repo:#{ENV.fetch("EXPECTED_REPOSITORY")}:environment:#{github_environment}"

checks = {
  "apiVersion" => config["apiVersion"] == "gitops.svc.plus/v1alpha1",
  "kind" => config["kind"] == "GitHubActionsOIDCConfig",
  "metadata.environment" => metadata["environment"] == environment,
  "metadata.provider" => metadata["provider"] == "gcp",
  "spec.project_id" => spec["project_id"] == expected_project,
  "spec.gcp_account_id" => account_id.match?(/\A[A-Za-z0-9][A-Za-z0-9._%+@-]{0,126}[A-Za-z0-9]\z/),
  "spec.organization_id" => spec["organization_id"].to_s == ENV.fetch("EXPECTED_ORGANIZATION_ID"),
  "spec.provider_url" => spec["provider_url"] == "https://token.actions.githubusercontent.com",
  "spec.audience" => spec["audience"].to_s.start_with?(expected_audience_prefix) || spec["audience"].to_s.start_with?(custom_audience_prefix),
  "spec.pool_id" => spec["pool_id"].to_s.match?(/\A[a-z][a-z0-9-]{0,31}\z/),
  "spec.provider_id" => spec["provider_id"].to_s.match?(/\A[a-z][a-z0-9-]{0,31}\z/),
  "spec.service_account_id" => spec["service_account_id"].to_s == "github-actions-#{environment}",
  "spec.repository" => spec["repository"] == ENV.fetch("EXPECTED_REPOSITORY"),
  "spec.subjects" => spec["subjects"].is_a?(Array) && spec["subjects"].include?(required_subject),
  "spec.state.bucket" => spec.dig("state", "bucket").to_s.match?(/\A[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]\z/),
  "spec.state.key" => spec.dig("state", "key") == expected_state_key
}
failed = checks.select { |_name, passed| !passed }.keys
abort "GCP OIDC declaration failed validation: #{failed.join(", ")}" unless failed.empty?

values = {
  "environment" => environment,
  "github_environment" => github_environment,
  "account_id" => account_id,
  "project_id" => spec.fetch("project_id"),
  "repository" => spec.fetch("repository"),
  "pool_id" => spec.fetch("pool_id"),
  "provider_id" => spec.fetch("provider_id"),
  "audience" => spec.fetch("audience"),
  "service_account_id" => spec.fetch("service_account_id"),
  "subjects_json" => JSON.generate(spec.fetch("subjects")),
  "state_bucket" => spec.dig("state", "bucket"),
  "state_key" => spec.dig("state", "key")
}
output = ENV["GITHUB_OUTPUT"]
if output
  File.open(output, "a") { |io| values.each { |key, value| io.puts "#{key}=#{value}" } }
end
puts JSON.generate(values)
RUBY
