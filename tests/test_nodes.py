from pathlib import Path
import importlib.util,json,tempfile,unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('verified_nodes',ROOT/'nodes.py')
nodes=importlib.util.module_from_spec(spec);spec.loader.exec_module(nodes)

class NodeTests(unittest.TestCase):
    def profile(self,root,stages=None):
        (root/'runner.py').write_text('pass\n',encoding='utf-8')
        path=root/'profile.json';path.write_text(json.dumps(dict(schema_version=1,project_root='.',
            runner='runner.py',state_directory='runs',stages=stages or ['Prepare','Verify'])),encoding='utf-8')
        return str(path)
    def test_generic_two_stage_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            profile=self.profile(Path(temp))
            plan=nodes.VerifiedPipelineSettings().build(profile,1,2)[0]
            for i in [1,2]:plan=nodes.VerifiedPipelineStage().append(plan,i)[0]
            self.assertEqual(plan['chain'],[1,2]);self.assertEqual(len(plan['profile']['stages']),2)
    def test_reject_out_of_order(self):
        with tempfile.TemporaryDirectory() as temp:
            plan=nodes.VerifiedPipelineSettings().build(self.profile(Path(temp)),1,2)[0]
            with self.assertRaisesRegex(ValueError,'order'):nodes.VerifiedPipelineStage().append(plan,2)
    def test_reject_invalid_subset(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):nodes.VerifiedPipelineSettings().build(self.profile(Path(temp)),2,1)
    def test_reject_changed_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            path=self.profile(Path(temp));plan=nodes.VerifiedPipelineSettings().build(path,1,2)[0]
            for i in [1,2]:plan=nodes.VerifiedPipelineStage().append(plan,i)[0]
            data=json.loads(Path(path).read_text());data['stages'][0]='Changed';Path(path).write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'changed'):nodes.VerifiedPipelineExecute().execute(plan,'run')
    def test_reject_runner_outside_project(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(self.profile(Path(temp)));data=json.loads(path.read_text());data['runner']='../outside.py';path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'within project'):nodes.load_profile(str(path))
    def test_incomplete_chain_cannot_start(self):
        with tempfile.TemporaryDirectory() as temp:
            plan=nodes.VerifiedPipelineSettings().build(self.profile(Path(temp)),1,2)[0]
            with self.assertRaisesRegex(ValueError,'Incomplete'):nodes.VerifiedPipelineExecute().execute(plan,'run')

if __name__=='__main__':unittest.main()
