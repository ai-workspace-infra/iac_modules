# Supabase Cloud Terraform support

This provider tree adds Supabase Cloud support to the repository's YAML-driven
IaC layout. It follows the repository's declaration → render → Terraform
workdir pattern and uses the official `supabase/supabase` provider.

## What is managed

- `supabase_project.this`: creates or imports a Supabase project.
- `supabase_pooler.this`: reads the official Session/Transaction Pooler URIs.
- `connection`: exposes the standard downstream contract:
  `username`, `database`, `uri`, and selected `mode`.

The provider manages the project and connection metadata; it does not create
arbitrary PostgreSQL users. Supabase's project database user is supplied by the
connection string returned by Supabase.

## Configuration contract

Declare non-secret values in the GitOps repository at
`resources/<project>/<env>/supabase/supabase.yaml`:

```yaml
global:
  project_ref: "{{ env.get('SUPABASE_PROJECT_REF', '') }}" # omit for a new project
  organization_id: "{{ env.get('SUPABASE_ORGANIZATION_ID', '') }}"
  project_name: "ai-workspace-dev"
  region: "ap-southeast-1"
  instance_size: "micro"
  pooler_mode: "session"

database:
  username: "{{ env.get('SUPABASE_DATABASE_USERNAME', 'postgres') }}"
  name: "postgres"
  uri_env: "SUPABASE_DATABASE_DIRECT_URL"
```

Do not put `SUPABASE_ACCESS_TOKEN`, database passwords, or connection URIs in
YAML, generated tfvars, or committed Terraform. Inject them from Vault/CI:

```bash
export SUPABASE_ACCESS_TOKEN="..."
export TF_VAR_database_password="..."
export TF_VAR_database_uri="postgresql://..." # optional Direct URI
```

`SUPABASE_PROJECT_REF` is optional when creating a new project and required
when adopting an existing project. `TF_VAR_database_uri` is optional. If
omitted, `database_uri` uses the configured Supavisor mode. Session mode
(`5432`) is the default for persistent
VPS backends; Transaction mode (`6543`) is intended for serverless clients that
have disabled prepared statements. Use a Direct URI for migrations and
backups.

## Standard init

From this directory:

```bash
./scripts/init.sh
terraform -chdir=envs/dev plan
terraform -chdir=envs/dev apply
terraform -chdir=envs/dev output -raw database_uri
```

`init.sh` renders the YAML and runs `terraform init`. When `project_ref` is
present, the renderer also writes an `import.tf` import block so an existing
Supabase project is adopted into state during the first plan/apply. The
generated files and state stay in `envs/<env>` and are ignored by Git.

For local Supabase CLI development, initialize the application repository
separately with `supabase init`; that local stack is not the Terraform-managed
Supabase Cloud project.
