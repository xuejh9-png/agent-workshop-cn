import json, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from runtime import WorkBuddyAdapter, ClaudeAdapter, save_workbuddy_key

class HostAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.script=self.root/'cli.py'
    def tearDown(self):self.temp.cleanup()
    def run_workbuddy(self,value):
        events=value if isinstance(value,list) else [dict(type='result',**value)]
        events=[dict(type='result',**x) if 'result' in x and 'type' not in x else x for x in events]
        init={'type':'system','subtype':'init','tools':['mcp__studio_files__list_files','mcp__studio_files__read_file']}
        lines=[init,*events]
        self.script.write_text('import sys,json\nsys.stdin.read()\n'+''.join('print('+repr(json.dumps(line))+',flush=True)\n' for line in lines))
        with patch('runtime.workbuddy_credentials',return_value=('CODEBUDDY_API_KEY','test-only')),patch('runtime.workbuddy_cli',return_value=str(self.script)),patch('runtime.shutil.which',return_value=sys.executable):
            return WorkBuddyAdapter(self.root).call('test','deepseek-v4.1-flash','low','probe',self.root,lambda e:None,lambda:False)
    def test_workbuddy_array_returns_only_terminal_result(self):
        value=[{'role':'user','content':[{'text':'private memory'}]}, {'type':'result','result':'连接正常','session_id':'new','usage':{'input_tokens':10},'is_error':False}]
        result=self.run_workbuddy(value)
        self.assertEqual(result['text'],'连接正常');self.assertEqual(result['sessionId'],'new')
        self.assertNotIn('private memory',json.dumps(result))
    def test_workbuddy_single_result_stays_compatible(self):
        self.assertEqual(self.run_workbuddy({'result':'ok','session_id':'s'})['text'],'ok')
    def test_workbuddy_array_without_completion_is_failure(self):
        with self.assertRaisesRegex(RuntimeError,'完成结果'):self.run_workbuddy([{'role':'user','text':'private'}])
    def test_workbuddy_empty_and_failed_results_are_not_success(self):
        for value in ({'result':'   '},{'is_error':True,'result':'failure'}):
            with self.assertRaises(RuntimeError):self.run_workbuddy(value)
    def test_workbuddy_unexecuted_tool_markup_fails(self):
        with self.assertRaisesRegex(RuntimeError,'未执行'):self.run_workbuddy({'result':'<DSML calls><invoke name="Bash">'})
    def test_rotated_credentials_invalidate_workbuddy_verification(self):
        with patch('runtime.workbuddy_cli',return_value='fake'),patch('runtime.workbuddy_credentials',return_value=('KEY','first')):
            before=WorkBuddyAdapter(self.root).identity()
        with patch('runtime.workbuddy_cli',return_value='fake'),patch('runtime.workbuddy_credentials',return_value=('KEY','second')):
            after=WorkBuddyAdapter(self.root).identity()
        self.assertNotEqual(before,after)
        self.assertNotIn('first',json.dumps(before));self.assertNotIn('second',json.dumps(after))
    def test_rotated_claude_credentials_invalidate_verification(self):
        with patch('runtime.claude_settings',return_value={'ANTHROPIC_BASE_URL':'https://test','ANTHROPIC_AUTH_TOKEN':'one'}):before=ClaudeAdapter(self.root).identity()
        with patch('runtime.claude_settings',return_value={'ANTHROPIC_BASE_URL':'https://test','ANTHROPIC_AUTH_TOKEN':'two'}):after=ClaudeAdapter(self.root).identity()
        self.assertNotEqual(before,after)
    def test_saved_key_is_private_and_does_not_echo(self):
        with patch('runtime.Path.home',return_value=self.root):value=save_workbuddy_key('test-only')
        path=self.root/'.workbuddy/api-key';self.assertEqual(path.stat().st_mode & 0o777,0o600)
        self.assertNotIn('test-only',json.dumps(value));self.assertEqual(path.read_text(),'test-only')
    def test_key_writer_refuses_links_without_touching_target(self):
        directory=self.root/'.workbuddy';directory.mkdir();outside=self.root/'outside';outside.write_text('preserve')
        (directory/'api-key').symlink_to(outside)
        with patch('runtime.Path.home',return_value=self.root),self.assertRaises(ValueError):save_workbuddy_key('test-only')
        self.assertEqual(outside.read_text(),'preserve')

if __name__=='__main__':unittest.main()
