from pathlib import Path
import copy
import importlib.util
import tempfile
import unittest
import yaml
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('database_render',ROOT/'scripts/render_contract.py')
render=importlib.util.module_from_spec(spec);spec.loader.exec_module(render)

class RenderTests(unittest.TestCase):
    def setUp(self):
        self.data={'global':{'management_mode':'existing_external','project_ref':'placeholderproject',
                  'strict_no_secret_state':True,'ack_sensitive_state':False,'explicit_adoption':False},
                   'database':{'username':'placeholder_runtime','name':'postgres'}}
    def run_render(self,data,root,name):
        source=root/(name+'.yaml');source.write_text(yaml.safe_dump(data));work=root/name
        render.render(type('Args',(),{'resources':source,'workdir':work})());return work
    def test_external_and_existing_workdir(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);work=self.run_render(self.data,root,'external')
            self.assertFalse((work/'import.tf').exists());self.assertFalse((work/'provider.tf').exists())
            self.assertNotIn('resource ',(work/'main.tf').read_text())
            with self.assertRaises(render.RenderRejected):self.run_render(self.data,root,'external')
    def test_managed_strict_and_explicit_modes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for mode in ('adopt_existing','create_new'):
                data=copy.deepcopy(self.data);g=data['global']
                g.update(management_mode=mode,explicit_adoption=mode=='adopt_existing',organization_id='placeholderorg',project_name='placeholderproject',region='placeholderregion')
                if mode=='create_new':g.pop('project_ref')
                with self.assertRaises(render.RenderRejected):self.run_render(data,root,'strict-'+mode)
                self.assertFalse((root/('strict-'+mode)).exists())
                g.update(strict_no_secret_state=False,ack_sensitive_state=True)
                work=self.run_render(data,root,mode)
                self.assertEqual((work/'import.tf').exists(),mode=='adopt_existing')
                self.assertNotIn('database_password',(work/'terraform.auto.tfvars.json').read_text())
    def test_secret_and_implicit_mode_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for key,value in [('password','PLACEHOLDER_ONLY'),('management_mode',None),('explicit_adoption',True)]:
                data=copy.deepcopy(self.data);data['global'][key]=value
                with self.assertRaises(render.RenderRejected):self.run_render(data,root,'bad-'+key)

if __name__=='__main__':unittest.main()
