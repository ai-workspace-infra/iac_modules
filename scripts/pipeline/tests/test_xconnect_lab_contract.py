import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "xconnect-lab-contract.py"
SPEC = importlib.util.spec_from_file_location("xconnect_lab_contract", SCRIPT)
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


class XConnectLabContractTests(unittest.TestCase):
    def test_state_key_is_exact_run_scoped(self):
        self.assertEqual(
            CONTRACT.state_key("xcl-123-2"),
            "terraform/uat/svc.plus/aws-cloud/primary/xconnect-lab/xcl-123-2/terraform.tfstate",
        )
        for value in ("uat", "xcl-123", "xcl-123-2-extra", "xcl-main-1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                CONTRACT.state_key(value)

    def test_ingress_is_bounded_to_unique_ipv4_hosts(self):
        self.assertEqual(CONTRACT.cidrs("35.79.83.48/32, 192.0.2.2/32", "test"),
                         ["35.79.83.48/32", "192.0.2.2/32"])
        for value in ("0.0.0.0/0", "35.79.83.48/24", "2001:db8::1/128",
                      "35.79.83.48/32,35.79.83.48/32",
                      "35.79.83.48/32,192.0.2.2/32,198.51.100.3/32"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                CONTRACT.cidrs(value, "test")

    def state(self, resources, child_modules=None):
        root = {"resources": resources}
        if child_modules is not None:
            root["child_modules"] = child_modules
        return {"values": {"root_module": root}}

    def guard(self, state):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "state.json").write_text(json.dumps(state))
            CONTRACT.guard_cleanup(folder, "xcl-123-2")

    def test_cleanup_accepts_only_owned_lab_resources(self):
        self.guard(self.state([
            {"address": "data.aws_vpc.uat", "mode": "data", "type": "aws_vpc", "values": {}},
            {"address": "aws_instance.gateway[0]", "type": "aws_instance",
             "values": {"tags_all": {"LabRun": "xcl-123-2"}}},
            {"address": "aws_security_group.client", "type": "aws_security_group",
             "values": {"tags_all": {"LabRun": "xcl-123-2"}}},
        ]))

    def test_cleanup_rejects_foreign_or_unexpected_state(self):
        cases = [
            self.state([{"address": "aws_instance.client", "type": "aws_instance",
                         "values": {"tags_all": {"LabRun": "xcl-999-1"}}}]),
            self.state([{"address": "aws_instance.production", "type": "aws_instance", "values": {}}]),
            self.state([{"address": "aws_instance.client", "type": "aws_instance", "values": {}}]),
            self.state([{"address": "aws_security_group.client", "type": "aws_security_group",
                         "values": {"tags_all": {}}}]),
            self.state([], child_modules=[{"address": "module.foreign"}]),
        ]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.guard(value)


if __name__ == "__main__":
    unittest.main()
