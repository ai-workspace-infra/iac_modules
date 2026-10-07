terraform {
  required_version = ">= 1.5.0"

  required_providers {
    supabase = {
      source  = "supabase/supabase"
      version = "= 1.11.0"
    }
  }
}

# The provider reads SUPABASE_ACCESS_TOKEN from the environment. Keeping the
# block argument-free avoids copying it into tfvars. This does not guarantee
# that provider diagnostics/state never retain sensitive values; review the pinned provider.
provider "supabase" {}
