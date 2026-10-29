"""Deterministic v1.2 tests: ownership, step persistence, settings, migration.

These do not replace the original M2 suite; they cover the v1.2 code paths that
the handoff review flagged (out-of-order reads, /api/run ownership, per-step
durability) without any real model call.
"""
import copy, json, tempfile, threading, time, unittest, uuid
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Studio
from v12 import Projects

MANAGER = 'test-model-a'
EMPLOYEE = 'test-model-b'
UNVERIFIED = 'test-model-c'
KEY = 'codex:acct-test:cfg-test:'


class FakeV12:
    """Scripted adapter. responses: dict|str|Exception, consumed per call."""

    def __init__(self):
        self.calls = []
        self.responses = []
        self.block_at = None
        self.blocked = threading.Event()

    def catalog(self, refresh=False):
        return [{'id': MANAGER, 'efforts': ['low']},
                {'id': EMPLOYEE, 'efforts': ['low', 'high']},
                {'id': UNVERIFIED, 'efforts': ['low']}]

    def account_identity(self):
        return {'accountId': 'acct-test', 'configId': 'cfg-test'}

    def cancel(self, ident):
        pass

    def call(self, ident, model, effort, prompt, cwd, event, cancelled,
             coordinator=False, writable=False):
        self.calls.append({'model': model, 'effort': effort, 'coordinator': coordinator,
                           'writable': writable, 'prompt': prompt})
        if self.block_at is not None and len(self.calls) == self.block_at:
            self.blocked.set()
            while not cancelled():
                time.sleep(.01)
            raise InterruptedError('stopped')
        item = self.responses.pop(0) if self.responses else {
            'route': 'answer', 'answer': '经理直接答复', 'tasks': [], 'task': '', 'reason': ''}
        if isinstance(item, BaseException):
            raise item
        text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        return {'text': text, 'usage': {'input_tokens': 10, 'output_tokens': 3},
                'sessionId': 'sess-' + str(len(self.calls)), 'requestedModel': model,
                'actualModel': None, 'role': 'coordinator' if coordinator else 'executor'}


def settings_v2():
    return {'schemaVersion': 2, 'revision': 0, 'productName': 'Agent Studio',
            'managerHost': 'codex',
            'managerModelByHost': {'codex': {'model': MANAGER, 'effort': 'low'}},
            'employeeProfilesByHost': {'codex': {'enabled': True, 'model': EMPLOYEE, 'effort': 'high'}},
            'reviewPolicy': {'enabled': False}, 'updatedAt': 'test'}


def delegate(*tasks):
    return {'route': 'delegate', 'answer': '安排给员工', 'reason': '测试',
            'task': '', 'tasks': [{'employee': e, 'task': t} for e, t in tasks]}


class V12Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Studio(Path(self.temp.name) / 'app')
        self.fake = FakeV12()
        self.app.adapter = self.fake
        self.pid = self.app.store.all('project')[0]['id']
        self.app.store.put('settings', 'v2', settings_v2())
        self.app.store.put('settings', 'verified_v2', {
            KEY + MANAGER: {'at': 'test'}, KEY + EMPLOYEE: {'at': 'test'}})

    def tearDown(self):
        for ident in list(self.app.workers):
            run = self.app.store.get('run', ident)
            if run and run['status'] not in ('completed', 'cancelled', 'failed', 'interrupted', 'blocked'):
                self.app.cancel(ident)
        self.app.store.db.close()
        self.temp.cleanup()

    # --- helpers ---------------------------------------------------------
    def start(self, **kw):
        body = {'schemaVersion': 2, 'projectId': self.pid, 'conversationId': None,
                'text': '你好', 'managerHost': 'codex', 'allowedEmployees': [],
                'allowWrite': False, 'requestId': uuid.uuid4().hex}
        body.update(kw)
        return self.app.start_v12(body)

    def wait(self, ident):
        self.app.workers[ident].join(5)
        return self.app.store.get('run', ident)

    # --- manager behaviour ----------------------------------------------
    def test_manager_direct_answer_uses_one_call(self):
        run = self.wait(self.start()['id'])
        self.assertEqual(run['route'], 'answer')
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(run['steps'], [])
        page = self.app.projects.page(run['conversationId'])
        self.assertEqual([m['role'] for m in page['messages']], ['user', 'assistant'])
        self.assertEqual(page['messages'][1]['text'], '经理直接答复')

    def test_delegate_without_allowed_employees_blocks_without_call(self):
        self.fake.responses = [delegate(('codex', '读一下资料'))]
        run = self.wait(self.start()['id'])
        self.assertEqual(run['status'], 'blocked')
        self.assertEqual(len(self.fake.calls), 1)
        self.assertIn('没有授权', run['answer'])

    def test_manager_cannot_plan_unallowed_employee(self):
        self.fake.responses = [delegate(('claude', '去外部逛一圈'))]
        run = self.wait(self.start(allowedEmployees=['codex'])['id'])
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(len(self.fake.calls), 1)
        self.assertIn('未被本次授权', run['error'])

    def test_plan_over_four_steps_rejected_before_any_employee(self):
        self.fake.responses = [delegate(*[('codex', '第%d步' % i) for i in range(5)])]
        run = self.wait(self.start(allowedEmployees=['codex'])['id'])
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(len(self.fake.calls), 1)

    def test_non_dict_manager_reply_fails_run_and_unblocks_queue(self):
        self.fake.responses = ['[{"x":1}]']
        run = self.wait(self.start()['id'])
        self.assertEqual(run['status'], 'failed')
        self.assertIn('结构无法解析', run['error'])
        # The next task must be accepted instead of hitting "已有任务执行中".
        follow = self.wait(self.start(text='再来一次')['id'])
        self.assertEqual(follow['status'], 'completed')

    def test_empty_manager_answer_is_a_failure_not_blank_success(self):
        self.fake.responses = [{'route': 'answer', 'answer': '   ', 'tasks': [], 'task': '', 'reason': ''}]
        run = self.wait(self.start()['id'])
        self.assertEqual(run['status'], 'failed')
        self.assertIn('空回答', run['error'])

    def test_file_routes_require_owning_project(self):
        other = self.app.projects.create_project('别的项目')
        self.assertEqual(self.app.workspace_for(self.pid), self.pid)
        self.assertEqual(self.app.workspace_for(self.pid, self.pid), self.pid)
        with self.assertRaises(ValueError):
            self.app.workspace_for(other['id'], self.pid)
        with self.assertRaises(ValueError):
            self.app.workspace_for('missing', self.pid)

    # --- per-step durability --------------------------------------------
    def test_later_failure_keeps_earlier_step_output(self):
        self.fake.responses = [delegate(('codex', '第一件事'), ('codex', '第二件事')),
                               '第一件事的结果', RuntimeError('第二步模型失败')]
        run = self.wait(self.start(allowedEmployees=['codex'])['id'])
        self.assertEqual(run['status'], 'failed')
        self.assertEqual([s['status'] for s in run['steps']], ['completed', 'failed'])
        self.assertEqual(run['steps'][0]['text'], '第一件事的结果')
        self.assertIn('第二步模型失败', run['steps'][1]['error'])
        self.assertEqual(run['answer'], '第一件事的结果')
        page = self.app.projects.page(run['conversationId'])
        steps = [m for m in page['messages'] if m.get('step')]
        self.assertEqual([m['step'] for m in steps], [1, 2])
        self.assertEqual(steps[0]['text'], '第一件事的结果')
        # The aggregate run message must not duplicate content carried by steps.
        self.assertEqual([m for m in page['messages'] if m['role'] == 'assistant' and not m.get('step')][0]['text'], '')

    def test_cancel_keeps_completed_step_and_marks_stopped_step(self):
        self.fake.responses = [delegate(('codex', '第一件事'), ('codex', '第二件事')), '第一件事的结果']
        self.fake.block_at = 3
        run = self.start(allowedEmployees=['codex'])
        self.assertTrue(self.fake.blocked.wait(5))
        cancelled = self.app.cancel(run['id'])
        self.assertEqual(cancelled['status'], 'cancelled')
        stored = self.app.store.get('run', run['id'])
        self.assertEqual([s['status'] for s in stored['steps']], ['completed', 'cancelled'])
        self.assertEqual(stored['steps'][0]['text'], '第一件事的结果')
        self.assertIn('第一件事的结果', stored['answer'])

    def test_step_messages_have_stable_sequence_and_no_duplicates(self):
        self.fake.responses = [delegate(('codex', '一'), ('codex', '二')), '结果一', '结果二']
        run = self.wait(self.start(allowedEmployees=['codex'])['id'])
        page = self.app.projects.page(run['conversationId'])
        sequences = [m['sequence'] for m in page['messages']]
        self.assertEqual(sequences, sorted(sequences))
        self.assertEqual(len(sequences), len(set(sequences)))
        self.assertEqual([m['id'] for m in page['messages'] if m.get('step')],
                         [run['id'] + ':step:1', run['id'] + ':step:2'])
        self.assertIn('任务1：', run['answer'])
        self.assertIn('任务2：', run['answer'])
        # Reading the page twice must not append records.
        before = len(self.app.projects.messages(run['conversationId']))
        self.app.projects.page(run['conversationId'])
        self.assertEqual(before, len(self.app.projects.messages(run['conversationId'])))

    def test_missing_step_message_is_reconciled_on_read(self):
        self.fake.responses = [delegate(('codex', '一'), ('codex', '二')), '结果一', '结果二']
        run = self.wait(self.start(allowedEmployees=['codex'])['id'])
        cid = run['conversationId']
        before = {m['id']: m for m in self.app.projects.messages(cid)}
        # Simulate a failed message write: the step is durable on the run only.
        self.app.store.db.execute("DELETE FROM records WHERE kind='message' AND id=?",
                                  (run['id'] + ':step:2',))
        self.app.store.db.commit()
        page = self.app.projects.page(cid)
        ids = [m['id'] for m in page['messages']]
        self.assertIn(run['id'] + ':step:2', ids)
        sequences = [m['sequence'] for m in page['messages']]
        self.assertEqual(sequences, sorted(sequences))
        self.assertEqual(len(sequences), len(set(sequences)))
        # Repair is idempotent: a second read must not add anything.
        again = self.app.projects.page(cid)
        self.assertEqual(ids, [m['id'] for m in again['messages']])
        # Existing rows keep their content.
        repaired = {m['id']: m for m in again['messages']}
        self.assertEqual(repaired[run['id'] + ':step:1']['text'], before[run['id'] + ':step:1']['text'])
        self.assertEqual(repaired[run['id'] + ':step:2']['text'], '结果二')

    def test_step_messages_are_reordered_by_step_number(self):
        self.fake.responses = [delegate(('codex', '一'), ('codex', '二')), '结果一', '结果二']
        run = self.wait(self.start(allowedEmployees=['codex'])['id'])
        cid = run['conversationId']
        first = self.app.store.get('message', run['id'] + ':step:1')
        second = self.app.store.get('message', run['id'] + ':step:2')
        first['sequence'], second['sequence'] = second['sequence'], first['sequence']
        self.app.store.put_many([('message', first['id'], first), ('message', second['id'], second)])
        page = self.app.projects.page(cid)
        steps = [m for m in page['messages'] if m.get('step')]
        self.assertEqual([m['step'] for m in steps], [1, 2])
        self.assertEqual(sorted(m['sequence'] for m in steps),
                         sorted([first['sequence'], second['sequence']]))

    def test_each_employee_step_uses_its_own_adapter(self):
        claude = FakeV12()
        claude.catalog = lambda refresh=False: [{'id': 'opus', 'efforts': ['low', 'high'], 'defaultEffort': 'high'}]
        claude.calls = []
        self.app.claude = claude
        settings = settings_v2()
        settings['employeeProfilesByHost']['claude'] = {'enabled': True, 'model': 'opus', 'effort': 'high'}
        self.app.store.put('settings', 'v2', settings)
        self.app.store.put('settings', 'verified_v2', {
            KEY + MANAGER: {'at': 'test'}, KEY + EMPLOYEE: {'at': 'test'},
            'claude:acct-test:cfg-test:opus': {'at': 'test'}})
        self.fake.responses = [delegate(('codex', '一'), ('claude', '二')), 'codex结果']
        # The Claude-side stub answers only the Claude employee step.
        claude.responses = ['claude结果']
        run = self.wait(self.start(allowedEmployees=['codex', 'claude'])['id'])
        self.assertEqual(run['status'], 'completed')
        self.assertEqual([c['model'] for c in self.fake.calls[1:]], [EMPLOYEE])
        self.assertEqual(len(claude.calls), 1)
        self.assertEqual(claude.calls[0]['model'], 'opus')
        self.assertIn('codex结果', run['steps'][0]['text'])
        self.assertIn('claude结果', run['steps'][1]['text'])

    # --- /api/run ownership ---------------------------------------------
    def test_run_for_rejects_other_project_and_unknown(self):
        run = self.wait(self.start()['id'])
        other = self.app.projects.create_project('另一个项目')
        self.assertEqual(self.app.run_for(run['id'], self.pid)['id'], run['id'])
        with self.assertRaises(ValueError):
            self.app.run_for(run['id'], other['id'])
        with self.assertRaises(ValueError):
            self.app.run_for('missing', self.pid)
        with self.assertRaises(ValueError):
            self.app.run_for(run['id'], 'no-such-project')
        # legacy run without projectId still resolves through its workspace
        legacy = {'id': 'legacy', 'workspace': self.pid, 'status': 'completed'}
        self.app.store.put('run', 'legacy', legacy)
        self.assertEqual(self.app.run_for('legacy', self.pid)['id'], 'legacy')

    def test_cancel_requires_owning_project(self):
        run = self.wait(self.start(text='机密内容')['id'])
        other = self.app.projects.create_project('别的项目')
        # Another project must not read or stop this run through /api/cancel.
        with self.assertRaises(ValueError):
            self.app.cancel(run['id'], other['id'])
        still = self.app.store.get('run', run['id'])
        self.assertEqual(still['status'], 'completed')
        result = self.app.cancel(run['id'], self.pid)
        self.assertNotIn('机密内容', json.dumps(result.get('error') or ''))
        self.assertEqual(result['id'], run['id'])
        # Internal shutdown paths call without a project and stay trusted.
        self.assertIsNotNone(self.app.cancel(run['id']))

    def test_cancel_http_requires_project_id(self):
        # Drive the real handler instead of asserting on source text.
        import threading, urllib.error, urllib.request
        from server import make_server
        srv = make_server(0, Path(self.temp.name) / 'http')
        srv.app.adapter = self.fake
        srv.app.store.put('settings', 'v2', settings_v2())
        srv.app.store.put('settings', 'verified_v2', {KEY + MANAGER: {'at': 't'}, KEY + EMPLOYEE: {'at': 't'}})
        pid = srv.app.store.all('project')[0]['id']
        thread = threading.Thread(target=srv.serve_forever, daemon=True); thread.start()
        host = '127.0.0.1:%d' % srv.server_port

        def call(path, body):
            request = urllib.request.Request('http://' + host + path, data=json.dumps(body).encode(),
                                             method='POST', headers={'Host': host, 'Content-Type': 'application/json',
                                                                     'X-Studio-Token': srv.app.token})
            try:
                with urllib.request.urlopen(request, timeout=10) as response: return response.status, json.load(response)
            except urllib.error.HTTPError as error: return error.code, json.load(error)

        try:
            _, run = call('/api/runs', {'schemaVersion': 2, 'projectId': pid, 'conversationId': None,
                                        'text': '取消归属', 'managerHost': 'codex', 'allowedEmployees': [],
                                        'allowWrite': False, 'requestId': 'http-cancel-1'})
            srv.app.workers[run['id']].join(5)
            status, body = call('/api/cancel', {'id': run['id']})
            self.assertEqual(status, 400)
            self.assertIn('缺少项目归属', body['error'])
            _, other = call('/api/projects', {'name': 'HTTP别的项目'})
            status, body = call('/api/cancel', {'id': run['id'], 'projectId': other['id']})
            self.assertEqual(status, 400)
            self.assertIn('不属于当前项目', body['error'])
            status, body = call('/api/cancel', {'id': run['id'], 'projectId': pid})
            self.assertEqual(status, 200)
            self.assertEqual(body['id'], run['id'])
        finally:
            srv.shutdown(); srv.server_close(); srv.app.store.db.close()

    def test_conversation_cannot_be_reused_across_projects(self):
        first = self.wait(self.start()['id'])
        other = self.app.projects.create_project('项目B')
        with self.assertRaises(ValueError):
            self.start(projectId=other['id'], conversationId=first['conversationId'])

    # --- progress and paging --------------------------------------------
    def test_progress_returns_only_changed_runs(self):
        run = self.wait(self.start()['id'])
        fresh = self.app.progress(run['conversationId'], self.pid, {})
        self.assertEqual([r['id'] for r in fresh['runs']], [run['id']])
        version = run['version']
        again = self.app.progress(run['conversationId'], self.pid, {run['id']: version})
        self.assertEqual(again['runs'], [])
        with self.assertRaises(ValueError):
            self.app.progress(run['conversationId'], self.pid, {run['id']: 'x'})
        with self.assertRaises(ValueError):
            self.app.progress('nope', self.pid, {})

    def test_conversation_paging_is_isolated(self):
        first = self.wait(self.start(text='第一个对话')['id'])
        second = self.wait(self.start(text='第二个对话')['id'])
        self.assertNotEqual(first['conversationId'], second['conversationId'])
        page = self.app.projects.page(first['conversationId'])
        self.assertEqual(page['conversation']['id'], first['conversationId'])
        self.assertTrue(all(m['conversationId'] == first['conversationId'] for m in page['messages']))
        self.assertEqual([m['text'] for m in page['messages'] if m['role'] == 'user'], ['第一个对话'])
        head = self.app.projects.page(first['conversationId'], limit=1)
        self.assertEqual(len(head['messages']), 1)
        self.assertEqual(head['before'], 2)
        older = self.app.projects.page(first['conversationId'], head['before'], limit=1)
        self.assertEqual(older['messages'][0]['role'], 'user')

    # --- settings --------------------------------------------------------
    def test_settings_save_bumps_revision_and_is_durable(self):
        saved = self.app.config.save(copy.deepcopy(self.app.config.get()))
        self.assertEqual(saved['revision'], 1)
        self.assertEqual(self.app.config.get()['revision'], 1)

    def test_settings_revision_conflict_leaves_store_untouched(self):
        stale = copy.deepcopy(self.app.config.get())
        body = copy.deepcopy(stale)
        body['managerModelByHost']['codex'] = {'model': EMPLOYEE, 'effort': 'high'}
        self.app.config.save(body)
        with self.assertRaises(ValueError):
            self.app.config.save(stale)
        stored = self.app.config.get()
        self.assertEqual(stored['revision'], 1)
        self.assertEqual(stored['managerModelByHost']['codex']['model'], EMPLOYEE)

    def test_settings_reject_unverified_model_and_unsupported_host(self):
        baseline = self.app.config.get()['revision']
        body = copy.deepcopy(self.app.config.get())
        body['managerModelByHost']['codex'] = {'model': UNVERIFIED, 'effort': 'low'}
        with self.assertRaises(ValueError):
            self.app.config.save(body)
        # Claude Code is now a real host, so an unconfigured (disabled, no model)
        # profile is allowed; saving must still reject an unverified enabled one.
        body = copy.deepcopy(self.app.config.get())
        body['employeeProfilesByHost']['claude'] = {'enabled': False, 'model': None, 'effort': 'low'}
        saved = self.app.config.save(body)
        self.assertIn('claude', saved['employeeProfilesByHost'])
        baseline = saved['revision']
        body = copy.deepcopy(self.app.config.get())
        body['employeeProfilesByHost']['claude'] = {'enabled': True, 'model': 'opus', 'effort': 'high'}
        with self.assertRaises(ValueError):
            self.app.config.save(body)
        # A host that is not wired at all is still refused outright.
        body = copy.deepcopy(self.app.config.get())
        body['employeeProfilesByHost']['workbuddy'] = {'enabled': False, 'model': None, 'effort': 'low'}
        with self.assertRaises(ValueError):
            self.app.config.save(body)
        body = copy.deepcopy(self.app.config.get())
        body['reviewPolicy'] = {'enabled': True}
        with self.assertRaises(ValueError):
            self.app.config.save(body)
        # Rejected saves must not move the stored revision.
        self.assertEqual(self.app.config.get()['revision'], baseline)

    def test_unsupported_manager_host_rejected_on_start(self):
        with self.assertRaises(ValueError):
            self.start(managerHost='claude')
        with self.assertRaises(ValueError):
            self.start(allowedEmployees=['workbuddy'])

    def test_request_fields_cannot_override_settings(self):
        with self.assertRaises(ValueError):
            self.start(model='test-model-b')
        with self.assertRaises(ValueError):
            self.start(schemaVersion=1)

    def test_request_nonce_is_idempotent(self):
        body = {'schemaVersion': 2, 'projectId': self.pid, 'conversationId': None,
                'text': '同一条请求', 'managerHost': 'codex', 'allowedEmployees': [],
                'allowWrite': False, 'requestId': 'fixed-nonce-1'}
        first = self.app.start_v12(body)
        self.wait(first['id'])
        replay = self.app.start_v12(dict(body))
        self.assertEqual(replay['id'], first['id'])
        self.assertEqual(len([r for r in self.app.store.all('run') if r['id'] == first['id']]), 1)
        with self.assertRaises(ValueError):
            self.app.start_v12({**body, 'text': '换了内容'})

    # --- migration -------------------------------------------------------
    def test_migration_is_idempotent(self):
        self.wait(self.start()['id'])
        counts = {k: len(self.app.store.all(k)) for k in
                  ('project', 'conversation', 'message', 'run_link')}
        Projects(self.app)
        again = {k: len(self.app.store.all(k)) for k in
                 ('project', 'conversation', 'message', 'run_link')}
        self.assertEqual(counts, again)

    def test_legacy_run_migrates_into_conversation(self):
        legacy = {'id': 'legacy-run', 'workspace': self.pid, 'text': '旧问题', 'answer': '旧回答',
                  'created': '2026-01-01T00:00:00+0800', 'status': 'completed', 'parent': None}
        self.app.store.put('run', 'legacy-run', legacy)
        Projects(self.app)
        link = self.app.store.get('run_link', 'legacy-run')
        self.assertEqual(link['projectId'], self.pid)
        messages = self.app.projects.messages(link['conversationId'])
        self.assertEqual([m['text'] for m in messages], ['旧问题', '旧回答'])
        self.assertEqual(self.app.store.get('run', 'legacy-run'), legacy)
        Projects(self.app)
        self.assertEqual(len(self.app.projects.messages(link['conversationId'])), 2)


if __name__ == '__main__':
    unittest.main()
