import json, tempfile, threading, time, unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import Studio
from runtime import CodexAdapter

class FakeAdapter:
    def __init__(self):self.calls=[];self.block=False;self.started=threading.Event();self.stopped=threading.Event()
    def catalog(self,refresh=False):return [{'id':'test-model-a','efforts':['low']},{'id':'test-model-b','efforts':['low','high']}]
    def call(self,ident,model,effort,prompt,cwd,event,cancelled,coordinator=False,writable=False):
        self.calls.append((model,effort,coordinator,writable,prompt));self.started.set()
        if self.block:
            while not cancelled():time.sleep(.01)
            self.stopped.set();raise InterruptedError('stopped')
        event({'type':'thread.started','role':'coordinator' if coordinator else 'executor'})
        text=json.dumps({'route':'answer','answer':'真实接口测试替身','task':'','reason':'短问答'}) if coordinator else '执行器测试替身'
        return {'text':text,'usage':{'input_tokens':10,'output_tokens':3},'sessionId':'fake-session','requestedModel':model,'actualModel':None,'role':'coordinator' if coordinator else 'executor'}
    def cancel(self,ident):pass

class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Studio(Path(self.temp.name)/'app');self.fake=FakeAdapter();self.app.adapter=self.fake;self.workspace=self.app.store.all('workspace')[0]['id']
        self.app.store.put('settings','verified',{'test-model-a':{'at':'test'},'test-model-b':{'at':'test'}})
        self.app.update_settings({'coordinatorModel':'test-model-a','coordinatorEffort':'low','executorModel':'test-model-b','executorEffort':'high','maxCalls':2})
    def tearDown(self):
        for ident in list(self.app.workers):
            r=self.app.store.get('run',ident)
            if r['status'] not in ('completed','cancelled','failed','interrupted'):self.app.cancel(ident)
        self.app.store.db.close();self.temp.cleanup()
    def start(self,**kw):return self.app.start({'workspace':self.workspace,'text':'你好','engine':'auto',**kw})
    def wait(self,ident):self.app.workers[ident].join(3);return self.app.store.get('run',ident)
    def test_direct_answer_one_model_no_files(self):
        r=self.wait(self.start()['id']);self.assertEqual(r['route'],'answer');self.assertEqual(r['kind'],'chat');self.assertEqual(len(self.fake.calls),1);self.assertEqual(r['files'],[]);self.assertEqual(r['calls'][0]['requestedModel'],'test-model-a')
    def test_explicit_model_and_effort_override(self):
        r=self.wait(self.start(engine='codex',model='test-model-b',effort='high')['id']);self.assertEqual(self.fake.calls[0][:4],('test-model-b','high',False,False));self.assertEqual(r['route'],'manual')
    def test_unverified_or_unknown_model_no_call(self):
        self.app.store.put('settings','verified',{})
        with self.assertRaises(ValueError):self.start(model='test-model-a')
        with self.assertRaises(ValueError):self.start(model='not-listed')
        self.assertEqual(self.fake.calls,[])
    def test_unsupported_engine_rejected(self):
        with self.assertRaises(ValueError):self.start(engine='workbuddy')
    def test_effort_rejected(self):
        with self.assertRaises(ValueError):self.start(model='test-model-a',effort='high')
    def test_cross_workspace_parent_rejected(self):
        parent=self.wait(self.start()['id']);other=self.app.workspace('另一个工作空间')
        with self.assertRaises(ValueError):self.app.start({'workspace':other['id'],'text':'你好','parent':parent['id']})
    def test_cancel_waits_worker_and_keeps_state(self):
        self.fake.block=True;r=self.start();self.assertTrue(self.fake.started.wait(2));cancelled=self.app.cancel(r['id']);self.assertEqual(cancelled['status'],'cancelled');self.assertTrue(self.fake.stopped.is_set());self.assertFalse(self.app.workers[r['id']].is_alive())
    def test_one_active_task(self):
        self.fake.block=True;r=self.start();self.fake.started.wait(2)
        with self.assertRaises(ValueError):self.start()
        self.app.cancel(r['id'])
    def test_write_scope_is_per_run(self):
        self.wait(self.start(engine='codex',allowWrite=True)['id']);self.wait(self.start(engine='codex')['id']);self.assertTrue(self.fake.calls[0][3]);self.assertFalse(self.fake.calls[1][3])
    def test_restart_marks_interrupted_without_retry(self):
        record={'id':'old','status':'running','created':'test'};self.app.store.put('run','old',record)
        restarted=Studio(Path(self.temp.name)/'app');self.assertEqual(restarted.store.get('run','old')['status'],'interrupted');restarted.store.db.close()
    def test_history_only_parent_chain(self):
        prior=self.wait(self.start(text='前文')['id']);self.wait(self.start(text='无关对话')['id']);child=self.start(parent=prior['id']);self.wait(child['id']);self.assertEqual(self.app.history(child)[0]['user'],'前文');self.assertEqual(len(self.app.history(child)),1)

if __name__=='__main__':unittest.main()
