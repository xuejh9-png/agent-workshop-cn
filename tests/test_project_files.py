"""Real filesystem boundary, proposal approval, conflict and recovery tests."""
import json, os, stat, tempfile, unittest
from unittest.mock import patch
from pathlib import Path
from server import Studio
from project_files import SourceFiles, SnapshotFiles, digest

class ProjectFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.app=Studio(self.root/'data');self.pid=self.app.store.all('project')[0]['id']
        self.source=self.root/'project';self.source.mkdir();(self.source/'app.py').write_text('print("before")\n')
        self.access=self.app.project_access;self.access.bind(self.pid,str(self.source))
    def tearDown(self):self.app.store.db.close();self.temp.cleanup()
    def proposal(self):
        self.app.store.put('run','r',{'id':'r','projectId':self.pid,'workspace':self.pid,'status':'completed','calls':[],'text':'change print'})
        self.access.prepare(self.pid,'r',['app.py']);snap=self.access.snapshot('r',self.pid)
        SnapshotFiles(snap['work'],True,None,snap['manifest']).create('app.py','print("after")\n')
        return self.access.proposals('r',self.pid)['changes'][0]
    def approve(self):
        value=self.access.proposals('r',self.pid)
        self.app.store.put('source_review','r',{'status':'approved','hashes':[x['afterHash'] for x in value['changes']]})
    def apply(self,item,revert=False):return self.access.apply('r',self.pid,'app.py',item['afterHash'],revert)
    def test_snapshot_proposal_never_changes_original(self):
        item=self.proposal();self.assertIn('+print("after")',item['diff'])
        self.assertEqual((self.source/'app.py').read_text(),'print("before")\n')
    def test_requires_review_and_exact_hash(self):
        item=self.proposal()
        with self.assertRaises(ValueError):self.apply(item)
        self.approve()
        with self.assertRaises(ValueError):self.access.apply('r',self.pid,'app.py','stale')
        self.assertEqual(self.apply(item)['status'],'applied')
    def test_apply_and_revert_are_idempotent(self):
        item=self.proposal();self.approve();self.apply(item);self.apply(item)
        self.assertEqual((self.source/'app.py').read_text(),'print("after")\n')
        self.apply(item,True);self.apply(item,True)
        self.assertEqual((self.source/'app.py').read_text(),'print("before")\n')
    def test_concurrent_edit_blocks_apply(self):
        item=self.proposal();self.approve();(self.source/'app.py').write_text('new work')
        with self.assertRaises(ValueError):self.apply(item)
        self.assertEqual((self.source/'app.py').read_text(),'new work')
    def test_concurrent_edit_blocks_revert(self):
        item=self.proposal();self.approve();self.apply(item);(self.source/'app.py').write_text('new work')
        with self.assertRaises(ValueError):self.apply(item,True)
        self.assertEqual((self.source/'app.py').read_text(),'new work')
    def test_cross_project_cannot_read_or_apply_proposal(self):
        item=self.proposal();other=self.app.projects.create_project('other')['id']
        with self.assertRaises(ValueError):self.access.proposals('r',other)
        with self.assertRaises(ValueError):self.access.apply('r',other,'app.py',item['afterHash'])
    def test_rebinding_revokes_old_proposals(self):
        item=self.proposal();self.approve();self.access.bind(self.pid,str(self.source))
        with self.assertRaises(ValueError):self.apply(item)
    def test_replaced_directory_is_rejected(self):
        old=self.root/'old';self.source.rename(old);self.source.mkdir()
        with self.assertRaises(ValueError):self.access.listing(self.pid)
    def test_symlink_and_hardlink_are_rejected(self):
        (self.source/'link.py').symlink_to(self.source/'app.py');os.link(self.source/'app.py',self.source/'hard.py')
        for name in ('link.py','hard.py','app.py'):
            with self.assertRaises((ValueError,OSError)):SourceFiles(self.source).read(name)
    def test_hidden_dependencies_and_credentials_are_excluded(self):
        for directory in ('.studio','node_modules'):
            (self.source/directory).mkdir();(self.source/directory/'private.py').write_text('private')
        (self.source/'api-key.txt').write_text('private');(self.source/'image.png').write_bytes(b'png')
        self.assertEqual([x['path'] for x in self.access.listing(self.pid)['files']],['app.py'])
        for name in ('.studio/private.py','node_modules/private.py','api-key.txt','../app.py'):
            with self.assertRaises(ValueError):SourceFiles(self.source).read(name)
    def test_snapshot_restricts_unselected_files_and_writes(self):
        self.access.prepare(self.pid,'r',['app.py']);snap=self.app.store.get('source_snapshot','r')
        files=SnapshotFiles(snap['work'],False,None,snap['manifest'])
        with self.assertRaises(ValueError):files.read('other.py')
        with self.assertRaises(PermissionError):files.create('app.py','changed')
    def test_crash_after_replace_is_reconciled(self):
        item=self.proposal();self.approve();self.apply(item)
        items=self.app.store.get('source_changes','r');items[0]['status']='applying';self.app.store.put('source_changes','r',items)
        self.assertEqual(self.access.proposals('r',self.pid)['changes'][0]['status'],'applied')
    def test_new_file_inode_blocks_apply_even_with_same_content(self):
        item=self.proposal();self.approve();temp=self.source/'replacement.py';temp.write_text('print("before")\n');temp.replace(self.source/'app.py')
        with self.assertRaises(ValueError):self.apply(item)
    def test_pending_run_cannot_freeze_incomplete_diffs(self):
        self.proposal();run=self.app.store.get('run','r');run['status']='running';self.app.store.put('run','r',run)
        with self.assertRaises(ValueError):self.access.proposals('r',self.pid)
        with self.assertRaises(ValueError):self.access.bind(self.pid,str(self.source))
    def test_invalid_file_selection_is_rejected(self):
        for names in ([],['app.py','app.py'],[{}],['../app.py']):
            with self.assertRaises((ValueError,TypeError)):self.access.prepare(self.pid,'r',names)
    def reviewer(self,text=None,session='independent'):
        class FakeReview:
            calls=[]
            def account_identity(self):return {'accountId':'review-account','configId':'review-config'}
            def catalog(self,refresh=False):return [{'id':'review-model','efforts':['high']}]
            def call(self,*args,**kwargs):
                self.calls.append((args,kwargs))
                return {'text':text if text is not None else '{"approved":true,"summary":"静态审核通过，未运行测试"}','sessionId':session,'usage':{}}
        fake=FakeReview();self.app.adapter=fake
        settings=self.app.config.get();settings['reviewPolicy']={'enabled':True,'host':'codex','model':'review-model','effort':'high'}
        self.app.store.put('settings','v2',settings)
        self.app.store.put('settings','verified_v2',{'codex:review-account:review-config:review-model':{'at':'test'}})
        return fake
    def test_fresh_readonly_review_is_required_before_original_write(self):
        item=self.proposal();fake=self.reviewer();self.access.review('r',self.pid);self.app.workers['review-r'].join(5)
        review=self.access.proposals('r',self.pid)['review'];self.assertEqual(review['status'],'approved')
        args,kw=fake.calls[0];self.assertFalse(kw['writable']);self.assertFalse(kw['coordinator'])
        self.assertNotIn('前序交接结果',args[3]);self.assertEqual(args[0],'review-r')
        self.assertEqual((self.source/'app.py').read_text(),'print("before")\n');self.apply(item)
    def test_missing_or_reused_review_session_does_not_approve(self):
        item=self.proposal();self.reviewer(session=None);self.access.review('r',self.pid);self.app.workers['review-r'].join(5)
        self.assertEqual(self.access.proposals('r',self.pid)['review']['status'],'failed')
        with self.assertRaises(ValueError):self.apply(item)
    def test_review_rejection_blocks_original_write(self):
        item=self.proposal();self.reviewer('{"approved":false,"summary":"存在问题"}');self.access.review('r',self.pid);self.app.workers['review-r'].join(5)
        self.assertEqual(self.access.proposals('r',self.pid)['review']['status'],'rejected')
        with self.assertRaises(ValueError):self.apply(item)
    def test_listing_does_not_claim_files_were_read(self):
        self.access.prepare(self.pid,'r',['app.py']);snap=self.app.store.get('source_snapshot','r');audit=self.root/'audit.jsonl'
        SnapshotFiles(snap['work'],False,audit,snap['manifest']).listing()
        self.assertFalse(audit.exists())
    def test_original_inode_is_retained_after_successful_write(self):
        item=self.proposal();self.approve();inode=(self.source/'app.py').stat().st_ino;self.apply(item)
        saved=Path(self.app.store.get('source_changes','r')[0]['recoveries'][-1])
        self.assertEqual(saved.stat().st_ino,inode);self.assertEqual(saved.read_text(),'print("before")\n')
    def test_save_at_last_check_is_restored_and_not_lost(self):
        item=self.proposal();self.approve();exchange=SourceFiles.exchange;count=0
        def racing_exchange(parent,left,right):
            nonlocal count
            if count==0:(self.source/'app.py').write_text('later editor work')
            count+=1;exchange(parent,left,right)
        with patch.object(SourceFiles,'exchange',side_effect=racing_exchange),self.assertRaisesRegex(ValueError,'同时编辑'):self.apply(item)
        self.assertEqual((self.source/'app.py').read_text(),'later editor work')
        backup=Path(self.app.store.get('source_changes','r')[0]['recoveries'][-1]);self.assertTrue(backup.exists())
    def test_backup_failure_retains_displaced_original(self):
        item=self.proposal();self.approve()
        with patch('project_files.os.replace',side_effect=OSError('disk unavailable')),self.assertRaisesRegex(ValueError,'恢复文件'):self.apply(item)
        record=self.app.store.get('source_changes','r')[0];self.assertEqual(record['status'],'conflict')
        self.assertEqual(Path(record['recoveries'][-1]).read_text(),'print("before")\n')
    def test_rollback_swap_failure_retains_concurrent_edit(self):
        item=self.proposal();self.approve();exchange=SourceFiles.exchange;count=0
        def fail_second(parent,left,right):
            nonlocal count
            count+=1
            if count==1:(self.source/'app.py').write_text('concurrent work');exchange(parent,left,right)
            else:raise OSError('swap failed')
        with patch.object(SourceFiles,'exchange',side_effect=fail_second),self.assertRaisesRegex(ValueError,'恢复文件'):self.apply(item)
        backup=Path(self.app.store.get('source_changes','r')[0]['recoveries'][-1]);self.assertEqual(backup.read_text(),'concurrent work')
    def test_directory_sync_failure_reconciles_completed_write(self):
        item=self.proposal();self.approve();sync=os.fsync
        def fail_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):raise OSError('directory sync failed')
            sync(fd)
        with patch('project_files.os.fsync',side_effect=fail_directory),self.assertRaisesRegex(ValueError,'同步确认失败'):self.apply(item)
        self.assertEqual(self.app.store.get('source_changes','r')[0]['status'],'applying')
        self.assertEqual(self.access.proposals('r',self.pid)['changes'][0]['status'],'applied')
        self.apply(item,True);self.assertEqual((self.source/'app.py').read_text(),'print("before")\n')

if __name__=='__main__':unittest.main()
