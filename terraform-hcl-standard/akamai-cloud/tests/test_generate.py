import json
import os
import subprocess
import yaml
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate  # noqa: E402


class GenerateTest(unittest.TestCase):
    def test_protected_volume_is_rendered_and_identity_bound_before_inventory(self):
        source = yaml.safe_load((ROOT / 'tests/fixtures/linode.yaml').read_text())
        source['global'].update(environment='prod', workspace='volume-test', state_namespace='volume-test')
        source['hosts'][0]['volume'] = {'label': 'retained-data', 'size': 100, 'filesystem': 'ext4'}
        volume = {'volume_id': 42, 'linode_id': 123, 'size_gb': 100, 'region': 'us-east',
                  'label': 'retained-data', 'filesystem_path': '/dev/disk/by-id/scsi-0Linode_Volume_retained-data'}
        with tempfile.TemporaryDirectory() as tempdir:
            resource = Path(tempdir) / 'prod.yaml'
            resource.write_text(yaml.safe_dump(source))
            workdir = Path(tempdir) / 'volume-test'
            generate.render(SimpleNamespace(resources=resource, workdir=workdir, namespace='volume-test'))
            hcl = (workdir / 'generated_hosts.tf').read_text()
            self.assertIn('/storage_protected"', hcl)
            self.assertIn('module.volume_web_node.filesystem_path', hcl)
            runtime = {'web-node': {'ip': '198.51.100.10', 'instance_id': 123, 'data_volume': volume}}
            with mock.patch.object(generate, 'terraform_output', return_value=runtime):
                generate.inventory(SimpleNamespace(resources=resource, workdir=workdir))
            facts = next(iter(json.loads((workdir / 'cmdb.json').read_text()).values()))
            self.assertEqual(facts['data_volume'], volume)
            self.assertEqual(facts['host_vars']['web_saas_data_device_path'], volume['filesystem_path'])
            runtime['web-node']['data_volume'] = {**volume, 'linode_id': 999}
            with mock.patch.object(generate, 'terraform_output', return_value=runtime), self.assertRaises(SystemExit):
                generate.inventory(SimpleNamespace(resources=resource, workdir=workdir))
            self.assertFalse((workdir / 'cmdb.json').exists())
            self.assertFalse((workdir / 'inventory.ini').exists())

    def test_missing_wrong_or_root_volume_facts_are_rejected(self):
        host = {'label': 'node', 'volume': {'label': 'data', 'size': 100}}
        volume = {'volume_id': 42, 'linode_id': 123, 'size_gb': 100, 'region': 'us-east',
                  'label': 'data', 'filesystem_path': '/dev/disk/by-id/scsi-0Linode_Volume_data'}
        bad = [None, {**volume, 'size_gb': 10}, {**volume, 'region': 'other'},
               {**volume, 'filesystem_path': '/dev/sda'}, {**volume, 'volume_id': True},
               {**volume, 'label': 'other'}]
        for sample in bad:
            with self.subTest(sample=sample), self.assertRaises(SystemExit):
                generate.validated_data_volume(host, {'instance_id': 123, 'data_volume': sample}, 'us-east')

    def test_paused_k3s_uses_node_name_and_preserves_service_alias(self):
        source=yaml.safe_load((ROOT/'tests/fixtures/linode.yaml').read_text())
        host=source['hosts'][0];name=host['name']
        host['host_vars']={'service_domains':['console.example.invalid']}
        with tempfile.TemporaryDirectory() as tmp:
            resource=Path(tmp)/'source.yaml';workdir=Path(tmp)/'work'
            resource.write_text(yaml.safe_dump(source))
            generate.render(SimpleNamespace(resources=resource,workdir=workdir,namespace='test'))
            runtime={name:{'ip':'198.51.100.10','instance_id':123}}
            with mock.patch.object(generate,'terraform_output',return_value=runtime):
                generate.inventory(SimpleNamespace(resources=resource,workdir=workdir))
            self.assertIn('console.example.invalid',json.loads((workdir/'cmdb.json').read_text()))
            host['host_vars'].update(k3s_platform_flux_bootstrap_mode='declarative_paused',k3s_platform_node_name=name)
            resource.write_text(yaml.safe_dump(source))
            with mock.patch.object(generate,'terraform_output',return_value=runtime):
                generate.inventory(SimpleNamespace(resources=resource,workdir=workdir))
            data=json.loads((workdir/'cmdb.json').read_text())
            self.assertEqual(list(data),[name])
            self.assertEqual(data[name]['fqdn'],'console.example.invalid')
            self.assertIn(name+' ',(workdir/'inventory.ini').read_text())
            host['host_vars']['k3s_platform_node_name']='another-node'
            resource.write_text(yaml.safe_dump(source))
            with mock.patch.object(generate,'terraform_output',return_value=runtime),self.assertRaises(SystemExit):
                generate.inventory(SimpleNamespace(resources=resource,workdir=workdir))
            self.assertFalse((workdir/'cmdb.json').exists())

    def test_firewall_label_is_stable_and_within_linode_limit(self):
        label = "open-platform-uat-ak-open-platform"
        rendered = generate.firewall_label(label)

        self.assertLessEqual(len(rendered), generate.LINODE_FIREWALL_LABEL_MAX)
        self.assertEqual(rendered, generate.firewall_label(label))
        self.assertNotEqual(rendered, label + "-firewall")

    def test_declared_firewall_label_is_rendered_and_invalid_labels_rejected(self):
        source = yaml.safe_load((ROOT / "tests/fixtures/linode.yaml").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            resource = Path(tmp) / "source.yaml"
            workdir = Path(tmp) / "work"
            source["hosts"][0]["firewall"]["label"] = "web-node-cold-20261031-fw"
            resource.write_text(yaml.safe_dump(source))
            generate.render(SimpleNamespace(resources=resource, workdir=workdir, namespace="test"))
            self.assertRegex((workdir / "generated_hosts.tf").read_text(), r'label\s*=\s*"web-node-cold-20261031-fw"')
            for label in ("bad--label", "-starts-wrong", "x" * 33, "bad\nlabel", ""):
                with self.subTest(label=label), self.assertRaises(SystemExit):
                    source["hosts"][0]["firewall"]["label"] = label
                    resource.write_text(yaml.safe_dump(source))
                    generate.load_sources(resource)

    def test_render_expands_explicit_linode_blocks(self):
        fixture = ROOT / "tests" / "fixtures" / "linode.yaml"
        with tempfile.TemporaryDirectory() as tempdir:
            workdir = Path(tempdir)
            generate.render(
                SimpleNamespace(resources=fixture, workdir=workdir, namespace="web-saas")
            )

            content = (workdir / "generated_hosts.tf").read_text(encoding="utf-8")
            self.assertNotIn('resource "linode_sshkey" "test_admin"', content)
            self.assertIn('authorized_keys = ["ssh-ed25519', content)
            self.assertIn('resource "linode_firewall" "fw_web_node"', content)
            self.assertIn('module "compute_web_node"', content)
            self.assertIn('/compute"', content)
            self.assertIn('ip          = module.compute_web_node.main_ip', content)
            self.assertNotRegex(content, r"\b(for_each|count|dynamic)\b")

            tfvars = json.loads((workdir / "terraform.auto.tfvars.json").read_text())
            self.assertEqual(tfvars["region"], "us-east")
            self.assertEqual(tfvars["type"], "g6-nanode-1")

            manifest = json.loads((workdir / "hosts_manifest.json").read_text())
            self.assertEqual(manifest["provider"], "akamai-cloud")
            self.assertEqual(manifest["state_namespace"], "web-saas")
            self.assertEqual(manifest["hosts"][0]["label"], "test-web-node")

    def test_inventory_preserves_groups_and_ssh_user_in_cmdb(self):
        fixture = ROOT / "tests" / "fixtures" / "linode.yaml"
        with tempfile.TemporaryDirectory() as tempdir:
            workdir = Path(tempdir)
            generate.render(
                SimpleNamespace(resources=fixture, workdir=workdir, namespace="web-saas")
            )
            with mock.patch.object(
                generate,
                "terraform_output",
                return_value={
                    "web-node": {
                        "ip": "198.51.100.10",
                        "private_ip": "10.0.0.10",
                        "ipv6": "2001:db8::10/128",
                        "instance_id": 123,
                    }
                },
            ):
                generate.inventory(SimpleNamespace(resources=fixture, workdir=workdir))

            cmdb = json.loads((workdir / "cmdb.json").read_text())
            self.assertEqual(cmdb["web.example.test"]["groups"], ["web", "debian"])
            self.assertEqual(cmdb["web.example.test"]["ansible_user"], "root")

    def test_inventory_and_firewall_preserve_regional_contract(self):
        source = yaml.safe_load((ROOT / "tests/fixtures/linode.yaml").read_text())
        host = source["hosts"][0]
        host["firewall"]["additional_tcp_ports"] = [1443]
        host["host_vars"].update(xconnect_region="sg", xconnect_pool="sg pool", xconnect_fqdn="sg-xconnect.onwalk.net", xconnect_open_to_users=False)
        with tempfile.TemporaryDirectory() as tempdir:
            resource = Path(tempdir) / "node.yaml"
            resource.write_text(yaml.safe_dump(source))
            workdir = Path(tempdir) / "workdir"
            generate.render(SimpleNamespace(resources=resource, workdir=workdir, namespace="web-saas"))
            self.assertRegex((workdir / "generated_hosts.tf").read_text(), r'ports\s*= "1443"')
            with mock.patch.object(generate, "terraform_output", return_value={"web-node": {"ip": "198.51.100.10"}}):
                generate.inventory(SimpleNamespace(resources=resource, workdir=workdir))
            inventory = json.loads(subprocess.check_output(["ansible-inventory", "-i", str(workdir / "inventory.ini"), "--list"], text=True))
            variables = inventory["_meta"]["hostvars"]["web.example.test"]
            self.assertEqual(variables["xconnect_pool"], "sg pool")
            self.assertEqual(variables["xconnect_region"], "sg")
            self.assertFalse(variables["xconnect_open_to_users"])
            self.assertEqual(variables["service_domains"], ["web.example.test"])

    def test_dev_inventory_refreshes_dynamic_ip_and_instance_identity(self):
        source = yaml.safe_load((ROOT / "tests/fixtures/linode.yaml").read_text())
        source["global"]["environment"] = "dev"
        with tempfile.TemporaryDirectory() as tempdir:
            resource = Path(tempdir) / "dev.yaml"
            resource.write_text(yaml.safe_dump(source))
            workdir = Path(tempdir) / "workdir"
            generate.render(SimpleNamespace(resources=resource, workdir=workdir, namespace="web-node"))
            for instance_id, ip in [(123, "198.51.100.10"), (456, "198.51.100.20")]:
                with mock.patch.object(generate, "terraform_output", return_value={"web-node": {"instance_id": instance_id, "ip": ip}}):
                    generate.inventory(SimpleNamespace(resources=resource, workdir=workdir))
                cmdb = json.loads((workdir / "cmdb.json").read_text())["web.example.test"]
                self.assertEqual((cmdb["instance_id"], cmdb["ip"]), (instance_id, ip))
                inventory = json.loads(subprocess.check_output(["ansible-inventory", "-i", str(workdir / "inventory.ini"), "--list"], text=True))
                self.assertEqual(inventory["_meta"]["hostvars"]["web.example.test"]["ansible_host"], ip)
                if instance_id == 456:
                    self.assertNotIn("198.51.100.10", (workdir / "inventory.ini").read_text())

    def test_dev_inventory_rejects_missing_or_other_host_runtime_before_publish(self):
        source = yaml.safe_load((ROOT / "tests/fixtures/linode.yaml").read_text())
        source["global"]["environment"] = "dev"
        invalid = [None, [], {}, {"production": {"instance_id": 123, "ip": "198.51.100.10"}}]
        invalid += [{"web-node": facts} for facts in [
            None, [], {}, {"instance_id": True, "ip": "198.51.100.10"},
            {"instance_id": 0, "ip": "198.51.100.10"},
            {"instance_id": 123}, {"instance_id": 123, "ip": "not-an-ip"},
            {"instance_id": 123, "ip": "127.0.0.1"},
            {"instance_id": 123, "ip": 123},
        ]]
        with tempfile.TemporaryDirectory() as tempdir:
            resource = Path(tempdir) / "dev.yaml"
            resource.write_text(yaml.safe_dump(source))
            workdir = Path(tempdir) / "workdir"
            generate.render(SimpleNamespace(resources=resource, workdir=workdir, namespace="web-node"))
            for runtime in invalid:
                # Reuse a successfully published workdir, as a retry would.
                with mock.patch.object(generate, "terraform_output", return_value={"web-node": {"instance_id": 123, "ip": "198.51.100.10"}}):
                    generate.inventory(SimpleNamespace(resources=resource, workdir=workdir))
                self.assertTrue((workdir / "cmdb.json").exists())
                with self.subTest(runtime=runtime), mock.patch.object(generate, "terraform_output", return_value=runtime):
                    with self.assertRaisesRegex(SystemExit, "dev CMDB"):
                        generate.inventory(SimpleNamespace(resources=resource, workdir=workdir))
                    self.assertFalse((workdir / "cmdb.json").exists())
                    self.assertFalse((workdir / "inventory.ini").exists())

    def test_dev_inventory_runtime_read_failure_invalidates_only_derived_outputs(self):
        source = yaml.safe_load((ROOT / "tests/fixtures/linode.yaml").read_text())
        source["global"]["environment"] = "dev"
        with tempfile.TemporaryDirectory() as tempdir:
            resource = Path(tempdir) / "dev.yaml"
            resource.write_text(yaml.safe_dump(source))
            workdir = Path(tempdir) / "workdir"
            generate.render(SimpleNamespace(resources=resource, workdir=workdir, namespace="web-node"))
            for artifact in ("cmdb.json", "inventory.ini", "terraform.tfstate", "unrelated.txt"):
                (workdir / artifact).write_text("preserve-unless-derived")
            with mock.patch.object(generate, "terraform_output", side_effect=SystemExit("read failed")):
                with self.assertRaisesRegex(SystemExit, "read failed"):
                    generate.inventory(SimpleNamespace(resources=resource, workdir=workdir))
            self.assertFalse((workdir / "cmdb.json").exists())
            self.assertFalse((workdir / "inventory.ini").exists())
            self.assertEqual((workdir / "terraform.tfstate").read_text(), "preserve-unless-derived")
            self.assertEqual((workdir / "unrelated.txt").read_text(), "preserve-unless-derived")

    def test_invalid_additional_tcp_ports_are_rejected(self):
        for port in [True, 0, 65536, "1443"]:
            with self.subTest(port=port), tempfile.TemporaryDirectory() as tempdir:
                source = yaml.safe_load((ROOT / "tests/fixtures/linode.yaml").read_text())
                source["hosts"][0]["firewall"]["additional_tcp_ports"] = [port]
                resource = Path(tempdir) / "node.yaml"
                resource.write_text(yaml.safe_dump(source))
                with self.assertRaises(SystemExit):
                    generate.load_sources(resource)

    def test_repo_workdir_must_match_namespace(self):
        fixture = ROOT / "tests" / "fixtures" / "linode.yaml"
        with self.assertRaises(SystemExit) as raised:
            generate.render(
                SimpleNamespace(
                    resources=fixture,
                    workdir=ROOT / "envs" / "uat",
                    namespace="web-saas",
                )
            )
        self.assertIn("shared", str(raised.exception))

    def test_render_rejects_multiple_hosts_in_one_namespace(self):
        fixture = ROOT / "tests" / "fixtures" / "linode.yaml"
        source = fixture.read_text(encoding="utf-8")
        duplicated_host = source.replace("environment: test", "environment: uat").replace(
            "  - name: web-node", "  - name: web-node-copy\n    region: us-east\n    type: g6-nanode-1\n    image: linode/debian12\n  - name: web-node", 1
        )
        with tempfile.TemporaryDirectory() as tempdir:
            resource = Path(tempdir) / "web-saas.yaml"
            resource.write_text(duplicated_host, encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                generate.render(
                    SimpleNamespace(
                        resources=resource,
                        workdir=Path(tempdir) / "workdir",
                        namespace="web-saas",
                    )
                )
        self.assertIn("exactly one host", str(raised.exception))

    def test_prod_render_allows_multiple_hosts_and_prevents_destroy(self):
        fixture = ROOT / "tests" / "fixtures" / "linode-prod.yaml"
        with tempfile.TemporaryDirectory() as tempdir:
            workdir = Path(tempdir)
            generate.render(
                SimpleNamespace(
                    resources=fixture,
                    workdir=workdir,
                    namespace="agent-proxy",
                )
            )

            content = (workdir / "generated_hosts.tf").read_text(encoding="utf-8")
            self.assertEqual(content.count('module "compute_'), 2)
            self.assertIn('/compute_protected"', content)
            self.assertNotIn('/compute"', content)

    def _prod_fixture_with_prevent_destroy(self, tempdir, value):
        source = yaml.safe_load((ROOT / "tests/fixtures/linode-prod.yaml").read_text())
        source["global"]["prevent_destroy"] = value
        resource = Path(tempdir) / "prod.yaml"
        resource.write_text(yaml.safe_dump(source), encoding="utf-8")
        return resource

    def test_prod_prevent_destroy_false_requires_explicit_renderer_authorization(self):
        with tempfile.TemporaryDirectory() as tempdir:
            resource = self._prod_fixture_with_prevent_destroy(tempdir, False)
            workdir = Path(tempdir) / "workdir"
            with self.assertRaisesRegex(SystemExit, "--allow-prod-replacement"):
                generate.render(SimpleNamespace(resources=resource, workdir=workdir))
            self.assertFalse((workdir / "generated_hosts.tf").exists())

    def test_explicit_prod_replacement_authorization_honors_false(self):
        with tempfile.TemporaryDirectory() as tempdir:
            resource = self._prod_fixture_with_prevent_destroy(tempdir, False)
            workdir = Path(tempdir) / "workdir"
            generate.render(
                SimpleNamespace(
                    resources=resource,
                    workdir=workdir,
                    allow_prod_replacement=True,
                )
            )
            content = (workdir / "generated_hosts.tf").read_text(encoding="utf-8")
            self.assertIn('/compute"', content)
            self.assertNotIn('/compute_protected"', content)

    def test_prod_prevent_destroy_requires_boolean_and_defaults_protected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            resource = self._prod_fixture_with_prevent_destroy(tempdir, "false")
            with self.assertRaisesRegex(SystemExit, "YAML boolean"):
                generate.render(
                    SimpleNamespace(resources=resource, workdir=Path(tempdir) / "invalid")
                )

            resource = ROOT / "tests/fixtures/linode-prod.yaml"
            workdir = Path(tempdir) / "default-protected"
            generate.render(SimpleNamespace(resources=resource, workdir=workdir))
            content = (workdir / "generated_hosts.tf").read_text(encoding="utf-8")
            self.assertIn('/compute_protected"', content)

    def test_provision_requires_and_audits_explicit_prod_replacement_authorization(self):
        repo_root = ROOT.parents[1]
        provision = repo_root / "scripts/selfhost/provision.sh"
        with tempfile.TemporaryDirectory() as tempdir:
            fake_bin = Path(tempdir) / "bin"
            fake_bin.mkdir()
            terraform = fake_bin / "terraform"
            terraform.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            terraform.chmod(0o755)
            resource = self._prod_fixture_with_prevent_destroy(tempdir, False)
            workdir = Path(tempdir) / "workdir"
            base_args = [
                str(provision), "--provider", "akamai-cloud", "--env", "prod",
                "--deployment-id", "renderer-test", "--resources", str(resource),
                "--workdir", str(workdir), "--phase", "verify",
            ]
            python_bin = str(Path(sys.executable).parent)
            env = {
                **os.environ,
                "PATH": f"{python_bin}:{fake_bin}:{os.environ['PATH']}",
            }
            denied = subprocess.run(base_args, env=env, capture_output=True, text=True)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("--allow-prod-replacement", denied.stderr)
            self.assertFalse((workdir / "generated_hosts.tf").exists())

            allowed = subprocess.run(
                [*base_args, "--allow-prod-replacement"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            receipt = json.loads(
                (Path(tempdir) / "receipts/renderer-test-provision-verify.json").read_text()
            )
            self.assertTrue(receipt["allow_prod_replacement"])


if __name__ == "__main__":
    unittest.main()
