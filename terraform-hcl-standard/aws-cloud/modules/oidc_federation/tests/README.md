# AWS OIDC mock tests

Run from the module directory with the CI version, Terraform 1.16.0:

```bash
terraform init -backend=false -input=false
terraform fmt -check -recursive
terraform validate
terraform test
```

All eight runs use `command = plan` and `mock_provider`; they require no AWS
credentials and perform no apply. Initial provider installation requires network.
Init keeps the locked provider version and may record a package hash for the
current platform; this is required when running Linux CI with a macOS-created lock.
The valid case checks the actual input statement structure, including the exact
aud/sub conditions and Federated principal, rather than trusting mock policy JSON.
Seven invalid-input runs expect variable validation failures.
Mocks are generated at plan time using `override_during = plan`, following the
[official provider mocking documentation](https://docs.hashicorp.com/terraform/language/tests/mocking).

Real AWS acceptance must independently verify AssumeRoleWithWebIdentity for the
allowed subject/audience, rejection of other identities, short credential lifetime
and least-privilege API permissions. This module does not attach permission policies.
Follow `platform-ops-toolkit/docs/howto/iam-integration-testing.md` for manual cases
and the redacted evidence template.
