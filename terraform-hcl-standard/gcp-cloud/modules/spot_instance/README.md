# GCP Spot instance

Single-instance module used by the AI Aggregator UAT renderer. The environment
root expands the five declared hosts into explicit module blocks; it does not
use `for_each`, `count`, or `dynamic` to control instances.

The module deliberately gives each UAT VM an ephemeral public address for
SSH/Ansible bootstrap. Firewall rules in the generated root restrict SSH to
the declared operator CIDR; CPA service ports are private-network-only.
