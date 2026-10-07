import importlib.util
import base64
import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[2] / "node_deploy"
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location("resolve_gcp_vault", SCRIPT_DIR / "resolve_gcp_vault.py")
resolver = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(resolver)
SOURCE_SPEC = importlib.util.spec_from_file_location(
    "resolve_gcp_vault_source", SCRIPT_DIR / "resolve_gcp_vault_source.py"
)
source_resolver = importlib.util.module_from_spec(SOURCE_SPEC)
assert SOURCE_SPEC.loader is not None
SOURCE_SPEC.loader.exec_module(source_resolver)


def fixture():
    declared = [
        {"name": f"vault-prod-{index}", "zone": f"asia-east1-{chr(97 + index)}", "xconnect_role": "gateway" if index == 0 else "one", "public_ip": True}
        for index in range(3)
    ]
    host_key = base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519" + b"\x00\x00\x00\x20" + b"0" * 32).decode()
    for node in declared:
        node["ssh_host_ed25519"] = host_key
    manifest = {
        "kind": "GCPWorkloadNamespace",
        "metadata": {"name": "vault-shared", "environment": "shared"},
        "spec": {"project_id": "open-platform-prod", "enable_oslogin": True, "enable_iap_ssh": False, "ssh_access_mode": "bootstrap-public", "ssh_source_ranges": ["35.79.83.48/32"], "resources": {"vault_nodes": declared}},
    }
    instances = [
        {"name": node["name"], "zone": node["zone"], "status": "RUNNING", "networkInterfaces": [{"networkIP": f"10.81.0.{index + 2}", "accessConfigs": [{"natIP": f"35.1.2.{index + 3}"}]}]}
        for index, node in enumerate(declared)
    ]
    service = {
        "kind": "VaultServerDeployment",
        "metadata": {"environment": "shared"},
        "spec": {
            "storage": {"backend": "raft", "address_scope": "private", "members": 3,
                        "leader": "vault-prod-0", "peers": ["vault-prod-1", "vault-prod-2"]},
            "nodes": [{"id": node["name"], "xconnect_role": node["xconnect_role"]} for node in declared],
            "stages": resolver.STAGES,
            "access": {"bootstrap": "bootstrap-public", "steady_state": "xconnect-zero",
                       "xconnect_topology": "vpn-overlay/shared/xconnect-vault-shared.yaml"},
        },
    }
    return manifest, service, instances


def raft_manifest():
    return {"spec": {"network_name": "vault-shared", "subnet_cidr": "10.81.0.0/20"}}


def raft_rule(ports=("8200", "8201"), sources=("10.81.0.0/20",), network="vault-shared", tags=("vault",), disabled=False):
    allowed = {"IPProtocol": "tcp"}
    if ports is not None:
        allowed["ports"] = list(ports)
    return {
        "name": "vault-shared-vault-raft-internal",
        "network": f"https://www.googleapis.com/compute/v1/projects/p/global/networks/{network}",
        "direction": "INGRESS",
        "disabled": disabled,
        "sourceRanges": list(sources),
        "targetTags": list(tags),
        "allowed": [allowed],
    }


class GcpVaultResolutionTests(unittest.TestCase):
    def test_resolves_public_ssh_and_private_raft_addresses(self):
        manifest, service, instances = fixture()
        result = resolver.resolve(manifest, service, instances, "open-platform-prod", "shared", "gha_1234567890")
        self.assertEqual(result["spec"]["nodes"][0]["address"], "35.1.2.3")
        self.assertEqual(result["spec"]["nodes"][0]["private_address"], "10.81.0.2")
        self.assertIn("vault_shared_leader", result["spec"]["nodes"][0]["groups"])
        self.assertIn("xconnect_one", result["spec"]["nodes"][1]["groups"])

    def test_rejects_wrong_project_or_missing_vm(self):
        manifest, service, instances = fixture()
        with self.assertRaises(ValueError):
            resolver.resolve(manifest, service, instances, "other-project", "shared", "gha_1234567890")
        with self.assertRaises(ValueError):
            resolver.resolve(manifest, service, instances[:2], "open-platform-prod", "shared", "gha_1234567890")

    def test_zero_trust_requires_assigned_overlay_ip_and_internal_dns(self):
        manifest, service, instances = fixture()
        manifest["spec"]["ssh_access_mode"] = "xconnect-zero"
        manifest["spec"]["ssh_source_ranges"] = []
        topology = {
            "kind": "XConnectOneNodeSet",
            "metadata": {"environment": "shared"},
            "spec": {
                "network": {"id": "net_shared_vault", "cidr": "10.79.0.0/24"},
                "control_plane": {"network_id": "net_shared_vault"},
                "gateway": {"id": "vault-prod-0", "xconnect": {"overlay_ip": "10.79.0.1", "internal_dns": "vault-prod-0.shared.internal"}},
                "fixed_nodes": [
                    {"id": "vault-prod-1", "xconnect": {"overlay_ip": "10.79.0.3", "internal_dns": "vault-prod-1.shared.internal"}},
                    {"id": "vault-prod-2", "xconnect": {"overlay_ip": "10.79.0.4", "internal_dns": "vault-prod-2.shared.internal"}},
                ],
            },
        }
        result = resolver.resolve(manifest, service, instances, "open-platform-prod", "shared", "gha_1234567890", topology)
        self.assertEqual(result["spec"]["nodes"][0]["address"], "vault-prod-0.shared.internal")
        self.assertEqual(result["spec"]["nodes"][0]["overlay_address"], "10.79.0.1")
        topology["spec"]["fixed_nodes"][0]["xconnect"].pop("internal_dns")
        with self.assertRaises(ValueError):
            resolver.resolve(manifest, service, instances, "open-platform-prod", "shared", "gha_1234567890", topology)

    def test_rejects_cross_environment_manifest_and_topology(self):
        manifest, service, instances = fixture()
        with self.assertRaisesRegex(ValueError, "environment"):
            resolver.resolve(manifest, service, instances, "open-platform-prod", "uat", "gha_1234567890")

    def test_migration_makes_every_new_node_a_peer_on_the_overlay(self):
        manifest, service, instances = fixture()
        service["spec"]["migration"] = {"raft_network": "overlay", "source": {"id": "legacy"}}
        topology = {
            "spec": {
                "network": {"cidr": "10.79.0.0/24"},
                "gateway": {"id": "vault-prod-0", "xconnect": {"overlay_ip": "10.79.0.1"}},
                "fixed_nodes": [
                    {"id": "vault-prod-1", "xconnect": {"overlay_ip": "10.79.0.3"}},
                    {"id": "vault-prod-2", "xconnect": {"overlay_ip": "10.79.0.4"}},
                ],
            },
        }
        result = resolver.resolve(manifest, service, instances, "open-platform-prod", "shared", "gha_1234567890", topology)
        for node in result["spec"]["nodes"]:
            self.assertIn("vault_shared_peers", node["groups"])
            self.assertNotIn("vault_shared_leader", node["groups"])
        self.assertNotIn("vault-shared-leader", result["spec"]["stages"])
        self.assertEqual(result["spec"]["nodes"][0]["private_address"], "10.79.0.1")
        self.assertEqual(result["spec"]["nodes"][0]["address"], "35.1.2.3")
        # Before Zero assigns an overlay IP the node keeps its VPC address, so
        # the XConnect stages can run; migrate-join refuses via raft-overlay.
        topology["spec"]["fixed_nodes"][1]["xconnect"] = {}
        result = resolver.resolve(manifest, service, instances, "open-platform-prod", "shared", "gha_1234567890", topology)
        pending = next(node for node in result["spec"]["nodes"] if node["id"] == "vault-prod-2")
        self.assertNotIn("overlay_address", pending)
        self.assertFalse(pending["private_address"].startswith("10.79."))
        topology["spec"]["fixed_nodes"][1]["xconnect"] = {"overlay_ip": "192.168.1.9"}
        with self.assertRaisesRegex(ValueError, "outside the declared overlay"):
            resolver.resolve(manifest, service, instances, "open-platform-prod", "shared", "gha_1234567890", topology)

    def test_contract_records_connection_mode(self):
        manifest, service, instances = fixture()
        result = resolver.resolve(manifest, service, instances, "open-platform-prod", "shared", "gha_1234567890")
        self.assertEqual(result["spec"]["connection"], {"mode": "bootstrap-public"})

    def test_private_raft_channel_matches_the_iac_rule(self):
        manifest = raft_manifest()
        resolver.verify_private_raft_channel(manifest, [raft_rule()])
        split = [raft_rule(ports=["8200"]), raft_rule(ports=["8201"])]
        resolver.verify_private_raft_channel(manifest, split)
        resolver.verify_private_raft_channel(manifest, [raft_rule(ports=["8200-8201"])])

    def test_private_raft_channel_must_exist_and_stay_private(self):
        manifest = raft_manifest()
        with self.assertRaisesRegex(ValueError, "8201"):
            resolver.verify_private_raft_channel(manifest, [raft_rule(ports=["8200"])])
        with self.assertRaisesRegex(ValueError, "no private Raft"):
            resolver.verify_private_raft_channel(manifest, [raft_rule(disabled=True)])
        with self.assertRaisesRegex(ValueError, "no private Raft"):
            resolver.verify_private_raft_channel(manifest, [raft_rule(network="other")])
        with self.assertRaisesRegex(ValueError, "no private Raft"):
            resolver.verify_private_raft_channel(manifest, [raft_rule(sources=["10.0.0.0/8"])])
        with self.assertRaisesRegex(ValueError, "exposes Vault port 8200 publicly"):
            resolver.verify_private_raft_channel(manifest, [raft_rule(), raft_rule(sources=["0.0.0.0/0"], ports=None)])
        public_all = raft_rule(sources=["0.0.0.0/0"])
        public_all["allowed"] = [{"IPProtocol": "all"}]
        with self.assertRaisesRegex(ValueError, "publicly"):
            resolver.verify_private_raft_channel(manifest, [raft_rule(), public_all])
        https = raft_rule(sources=["0.0.0.0/0"], ports=["443"], tags=["vault-gateway"])
        resolver.verify_private_raft_channel(manifest, [raft_rule(), https])

    def test_rejects_provider_nodes_that_differ_from_service_declaration(self):
        manifest, service, instances = fixture()
        manifest["spec"]["resources"]["vault_nodes"][1]["xconnect_role"] = "gateway"
        with self.assertRaisesRegex(ValueError, "provider-neutral"):
            resolver.resolve(manifest, service, instances, "open-platform-prod", "shared", "gha_1234567890")

    def test_resolves_single_declared_gateway(self):
        manifest, service, instances = fixture()
        manifest["spec"]["resources"]["vault_nodes"] = manifest["spec"]["resources"]["vault_nodes"][:1]
        instances = instances[:1]
        service["spec"]["storage"] = {"backend": "raft", "address_scope": "private", "members": 1,
                                        "leader": "vault-prod-0", "peers": []}
        service["spec"]["nodes"] = service["spec"]["nodes"][:1]
        result = resolver.resolve(manifest, service, instances, "open-platform-prod", "shared", "gha_1234567890")
        self.assertEqual([node["id"] for node in result["spec"]["nodes"]], ["vault-prod-0"])

    def test_resolves_single_migration_peer_when_source_remains_gateway(self):
        manifest, service, instances = fixture()
        manifest["spec"]["resources"]["vault_nodes"] = [manifest["spec"]["resources"]["vault_nodes"][1]]
        manifest["spec"]["resources"]["vault_nodes"][0]["name"] = "vault-shared-0"
        manifest["spec"]["resources"]["vault_nodes"][0]["xconnect_role"] = "one"
        manifest["spec"]["resources"]["vault_nodes"][0]["zone"] = "asia-east1-a"
        instances = [{**instances[1], "name": "vault-shared-0", "zone": "asia-east1-a"}]
        service["spec"]["migration"] = {"source": {"id": "vault-prod-0"}, "raft_network": "overlay"}
        service["spec"]["storage"] = {"backend": "raft", "address_scope": "private", "members": 1,
                                        "leader": "vault-prod-0", "peers": ["vault-shared-0"]}
        service["spec"]["nodes"] = [{"id": "vault-shared-0", "xconnect_role": "one"}]
        topology = {
            "spec": {
                "network": {"cidr": "10.79.0.0/24"},
                "gateway": {"id": "vault-prod-0", "xconnect": {"overlay_ip": "10.79.0.1"}},
                "fixed_nodes": [{"id": "vault-shared-0", "xconnect": {"overlay_ip": "10.79.0.10"}}],
            },
        }
        result = resolver.resolve(manifest, service, instances, "open-platform-prod", "shared", "gha_1234567890", topology)
        node = result["spec"]["nodes"][0]
        self.assertEqual(node["id"], "vault-shared-0")
        self.assertIn("xconnect_one", node["groups"])
        self.assertIn("vault_shared_peers", node["groups"])
        self.assertEqual(node["private_address"], "10.79.0.10")
        service["spec"]["storage"]["leader"] = "vault-shared-0"
        service["spec"]["storage"]["peers"] = []
        after = resolver.resolve(manifest, service, instances, "open-platform-prod", "shared", "gha_1234567890", topology)
        self.assertEqual(after["spec"]["nodes"][0]["private_address"], "10.79.0.10")

    def test_rejects_two_node_scale(self):
        manifest, service, instances = fixture()
        manifest["spec"]["resources"]["vault_nodes"] = manifest["spec"]["resources"]["vault_nodes"][:2]
        instances = instances[:2]
        service["spec"]["storage"]["members"] = 2
        service["spec"]["storage"]["peers"] = ["vault-prod-1"]
        service["spec"]["nodes"] = service["spec"]["nodes"][:2]
        with self.assertRaisesRegex(ValueError, "one or three"):
            resolver.resolve(manifest, service, instances, "open-platform-prod", "shared", "gha_1234567890")


class SourceResolverTests(unittest.TestCase):
    def test_source_identity_and_reviewed_address_are_preserved(self):
        host_key = base64.b64encode(
            b"\x00\x00\x00\x0bssh-ed25519" + b"\x00\x00\x00\x20" + b"1" * 32
        ).decode()
        config = {
            "source_id": "vault-source-0",
            "source_zone": "asia-east1-a",
            "project_id": "open-platform-prod",
            "network_name": "vault-shared",
            "expected_address": "35.1.2.3",
            "ssh_host_ed25519": host_key,
            "environment": "shared",
            "overlay_address": "10.79.0.10",
            "xconnect_role": "one",
        }
        instances = [{
            "name": "vault-source-0",
            "zone": "https://compute.googleapis.com/compute/v1/projects/open-platform-prod/zones/asia-east1-a",
            "status": "RUNNING",
            "networkInterfaces": [{
                "network": "https://compute.googleapis.com/compute/v1/projects/open-platform-prod/global/networks/vault-shared",
                "networkIP": "10.81.0.9",
                "accessConfigs": [{"natIP": "35.1.2.3"}],
            }],
        }]
        contract = source_resolver.resolve(config, instances, "gha_1234567890")
        node = contract["spec"]["nodes"][0]
        self.assertEqual(node["address"], "35.1.2.3")
        self.assertEqual(node["private_address"], "10.79.0.10")
        self.assertEqual(node["auth"], {"adapter": "gcp-oslogin-ephemeral"})

        config["expected_address"] = "35.1.2.4"
        with self.assertRaisesRegex(ValueError, "differs from the reviewed migration source"):
            source_resolver.resolve(config, instances, "gha_1234567890")


if __name__ == "__main__":
    unittest.main()
