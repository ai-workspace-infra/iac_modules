import copy
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('verify_dev_sit_target', ROOT / 'scripts/verify_dev_sit_target.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TargetTest(unittest.TestCase):
    def setUp(self):
        self.cmdb = {'dev-k3s-v5': {'name':'dev-k3s-v5','label':'dev-k3s-v5','instance_id':'123','ip':'8.8.8.8'}}
        self.provider = {'id':123,'label':'dev-k3s-v5','region':'jp-tyo-3','status':'running','ipv4':['8.8.8.8']}

    def test_same_exact_running_host(self):
        self.assertEqual(module.validate(self.cmdb, self.provider, '123'), '8.8.8.8')

    def test_mismatch_never_returns_a_target(self):
        for change in ({'id':124}, {'label':'production'}, {'region':'other'}, {'status':'offline'}, {'ipv4':['8.8.4.4']}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                body = dict(self.provider, **change)
                module.validate(self.cmdb, body, '123')
        for change in ({'ip':'10.0.0.1'}, {'label':'production'}, {'instance_id':'124'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                cmdb = copy.deepcopy(self.cmdb); cmdb['dev-k3s-v5'].update(change)
                module.validate(cmdb, self.provider, '123')

    def test_single_get_and_redacted_output(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'cmdb.json';path.write_text(json.dumps(self.cmdb));output=io.StringIO()
            with patch.object(sys,'argv',['verify','--cmdb',str(path),'--instance-id','123']), patch.dict('os.environ',{'LINODE_TOKEN':'test-secret'}), patch.object(module,'_linode_get_one',return_value=(200,self.provider)) as lookup, contextlib.redirect_stdout(output):
                self.assertEqual(module.main(),0)
            lookup.assert_called_once_with('linode/instances/123','test-secret')
            self.assertNotIn('test-secret',output.getvalue())
            self.assertEqual(json.loads(output.getvalue())['result'],'MATCH')


if __name__ == '__main__':
    unittest.main()
