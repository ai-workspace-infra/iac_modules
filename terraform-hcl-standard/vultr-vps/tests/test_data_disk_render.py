import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("generate", ROOT / "scripts/generate.py")
generate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate)


class DataDiskRender(unittest.TestCase):
    def test_disk_attaches_only_to_declared_instance(self):
        host = {"name": "acceptance", "label": "acceptance", "region": "nrt",
                "plan": "vc2-2c-2gb", "os_id": 477, "tf_tags": [],
                "data_disk": {"size_gb": 25, "block_type": "high_perf"}}
        rendered = generate._jinja().get_template("hosts.tf.j2").render(ssh_keys=[], hosts=[host])
        self.assertIn('size_gb              = 25', rendered)
        self.assertIn('attached_to_instance = module.compute_acceptance.instance_id', rendered)
        self.assertIn('live                 = true', rendered)
        self.assertIn('region               = "nrt"\n', rendered)
        self.assertNotIn('for_each', rendered.split('resource "vultr_block_storage"')[1])

    def test_existing_hosts_do_not_get_disks(self):
        host = {"name": "existing", "label": "existing", "plan": "vc2-2c-2gb",
                "region": "nrt", "os_id": 477, "tf_tags": []}
        rendered = generate._jinja().get_template("hosts.tf.j2").render(ssh_keys=[], hosts=[host])
        self.assertNotIn('resource "vultr_block_storage"', rendered)


if __name__ == "__main__":
    unittest.main()
