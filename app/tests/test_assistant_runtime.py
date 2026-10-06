import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import assistant_runtime as runtime
import assistant_store as store
import assistant_tools as tools


class FakeProvider:
    def __init__(self, responses=None, blocked=False):
        self.responses = responses or [[{'type': 'text', 'text': '已检查对象 a。'}]]
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        if not blocked:
            self.release.set()

    def get_public(self):
        return {'key_configured': True, 'config': {'model': 'fake', 'timeout': 10}}

    def stream_completion(self, messages, catalog, cancel, deadline):
        index = len(self.calls)
        self.calls.append(copy.deepcopy(messages))
        self.entered.set()
        while not self.release.wait(.01):
            if cancel.is_set():
                raise InterruptedError()
        yield from self.responses[min(index, len(self.responses) - 1)]


class AssistantRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'runtime.sqlite'
        self.inventory = {'objects': [{'id': 'a', 'name': 'Alpha', 'kind': 'mcp', 'source': '测试'},
                                      {'id': 'b', 'name': 'Private', 'kind': 'skill', 'source': '测试'}],
                          'relations': []}
        self.providers = []
        self.runs = []
        store.initialize(self.connection)
        runtime.initialize(self.connection)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def tearDown(self):
        for rid in self.runs:
            runtime.cancel_run(self.connection, rid)
        for provider in self.providers:
            provider.release.set()
        for rid in self.runs:
            self.wait(rid)
        self.temp.cleanup()

    def session(self, sid=None):
        action, body = ('get', {'id': sid}) if sid else ('create', {'target_id': 'a'})
        result, status = store.dispatch(self.connection, '/api/assistant/' + action, body, self.inventory['objects'])
        self.assertEqual(status, 200)
        return result['session']

    def start(self, sid, provider, request_id='one', text='检查'):
        self.providers.append(provider)
        result, status = runtime.start(self.connection,
            {'session_id': sid, 'request_id': request_id, 'text': text, 'allow_context': True},
            self.inventory, provider, tools)
        if 'run' in result:
            self.runs.append(result['run']['id'])
        return result, status

    def wait(self, rid):
        until = time.monotonic() + 5
        while time.monotonic() < until:
            with runtime.LOCK:
                active = rid in runtime.ACTIVE
            result, status = runtime.get(self.connection, rid)
            if status == 200 and result['run']['status'] in runtime.TERMINAL and not active:
                return result
            time.sleep(.01)
        self.fail('运行未及时结束：' + rid)

    def test_completed_answer_persists_to_original_session_and_events_resume(self):
        sid = self.session()['id']
        other = self.session()['id']
        provider = FakeProvider(responses=[[{'type': 'text', 'text': '答'}, {'type': 'text', 'text': '案'},
                                            {'type': 'usage', 'usage': {'total_tokens': 3}}]])
        result, status = self.start(sid, provider)
        self.assertEqual(status, 202)
        rid = result['run']['id']
        final = self.wait(rid)
        self.assertEqual(final['run']['status'], 'succeeded')
        self.assertEqual(final['run']['answer'], '答案')
        self.assertEqual(final['run']['usage']['total_tokens'], 3)
        session = self.session(sid)
        self.assertEqual([m['text'] for m in session['messages']], ['检查', '答案'])
        self.assertTrue(all(m['run_id'] == rid for m in session['messages']))
        self.assertIsNone(session['active_run_id'])

        self.assertEqual(self.session(other)['messages'], [])
        events = final['events']
        self.assertEqual([e['seq'] for e in events], list(range(1, len(events) + 1)))
        resumed, _ = runtime.get(self.connection, rid, after=events[1]['seq'])
        self.assertEqual(resumed['events'], events[2:])

    def test_multiple_targets_authorize_union_not_unrelated_inventory(self):
        self.inventory['objects'] += [{'id':'c','name':'Related','kind':'directory'}, {'id':'d','name':'Unrelated','kind':'software'}]
        self.inventory['relations'] = [{'from':'b','to':'c','label':'uses'}]
        payload, status = store.dispatch(self.connection, '/api/assistant/create', {'target_ids':['a','b']}, self.inventory['objects'])
        self.assertEqual(status, 200)
        provider=FakeProvider()
        result, status=self.start(payload['session']['id'],provider)
        self.assertEqual(status,202)
        final=self.wait(result['run']['id'])['run']
        self.assertEqual(final['allowed_ids'],['a','b','c'])
        self.assertEqual([o['id'] for o in final['targets']],['a','b'])
        self.assertIn('selected_objects', json.dumps(provider.calls,ensure_ascii=False))

    def test_directory_terminal_cursor_reaches_provider_and_persisted_trace(self):
        import directory_browser
        from types import SimpleNamespace

        class PagingProvider(FakeProvider):
            def stream_completion(self, messages, catalog, cancel, deadline=None):
                self.calls.append(copy.deepcopy(messages))
                results=[json.loads(m['content']) for m in messages if m['role']=='tool']
                cursor=results[-1]['next_cursor'] if results else ''
                if cursor is None:
                    yield {'type':'text','text':'已读取到末页。'}
                else:
                    yield {'type':'tool_call','id':'page-'+str(len(results)), 'name':'list_directory',
                           'arguments':json.dumps({'object_id':'a','cursor':cursor})}

        for count in (0,21):
            with self.subTest(entries=count):
                directory=Path(self.temp.name)/('files-'+str(count));directory.mkdir()
                for i in range(count):(directory/f'item-{i:02}.txt').touch()
                self.inventory={'objects':[{'id':'a','name':'Files','kind':'directory','path':str(directory)}], 'relations':[]}
                provider=PagingProvider()
                with patch.object(directory_browser.psutil,'disk_partitions',return_value=[
                        SimpleNamespace(mountpoint=directory.anchor,opts='rw')]):
                    started,status=self.start(self.session()['id'],provider,text='列出全部当前层条目')
                    self.assertEqual(status,202)
                    final=self.wait(started['run']['id'])
                self.assertEqual(final['run']['status'],'succeeded')
                delivered=[json.loads(m['content']) for m in provider.calls[-1] if m['role']=='tool']
                persisted=[e['result'] for e in final['events'] if e['type']=='tool_finished']
                self.assertEqual(delivered,persisted)
                self.assertEqual(sum(len(p['entries']) for p in delivered),count)
                self.assertEqual(len(delivered),1 if count==0 else 2)
                self.assertIsNone(delivered[-1]['next_cursor'])
                self.assertFalse(delivered[-1]['truncated'])
                self.assertTrue(delivered[-1]['enumeration_complete'])
                self.assertEqual(delivered[-1]['read_errors'],0)

    def test_duplicate_request_during_and_after_completion_is_idempotent(self):
        sid = self.session()['id']
        provider = FakeProvider(blocked=True)
        result, _ = self.start(sid, provider)
        rid = result['run']['id']
        self.assertTrue(provider.entered.wait(2))
        retry, status = self.start(sid, provider)
        self.assertEqual(status, 200)
        self.assertEqual(retry['run']['id'], rid)
        self.assertEqual(self.start(sid, provider, text='其他内容')[1], 409)
        provider.release.set()
        self.wait(rid)
        self.assertEqual(self.start(sid, provider)[1], 200)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(len(self.session(sid)['messages']), 2)

    def test_idempotent_retry_works_when_two_slots_are_full(self):
        sid = self.session()['id']
        provider = FakeProvider(blocked=True)
        first, _ = self.start(sid, provider)
        self.start(self.session()['id'], FakeProvider(blocked=True))
        retry, status = self.start(sid, provider)
        self.assertEqual(status, 200)
        self.assertEqual(retry['run']['id'], first['run']['id'])

    def test_cancel_persists_terminal_state_and_clears_session_activity(self):
        sid = self.session()['id']
        provider = FakeProvider(blocked=True)
        result, _ = self.start(sid, provider)
        rid = result['run']['id']
        self.assertTrue(provider.entered.wait(2))
        result, status = runtime.cancel_run(self.connection, rid)
        self.assertEqual(status, 200)
        self.assertTrue(result['cancellation_requested'])
        self.assertEqual(self.wait(rid)['run']['status'], 'cancelled')
        session = self.session(sid)
        self.assertIsNone(session['active_run_id'])
        self.assertEqual(session['messages'][-1]['status'], 'cancelled')

    def test_restart_marks_unfinished_task_interrupted_without_replay(self):
        sid = self.session()['id']
        provider = FakeProvider()
        with patch.object(runtime.threading, 'Thread'):
            result, _ = self.start(sid, provider)
        rid = result['run']['id']
        with runtime.LOCK:
            runtime.ACTIVE.pop(rid, None)
        runtime.initialize(self.connection)
        runtime.initialize(self.connection)
        final = self.wait(rid)
        self.assertEqual(final['run']['status'], 'interrupted')
        session = self.session(sid)
        self.assertIsNone(session['active_run_id'])
        self.assertEqual(len(session['messages']), 2)
        self.assertEqual(session['messages'][-1]['status'], 'interrupted')
        self.assertEqual(provider.calls, [])

    def test_model_cannot_expand_fixed_tool_scope(self):
        sid = self.session()['id']
        provider = FakeProvider(responses=[[
            {'type': 'tool_call', 'id': 'call1', 'name': 'get_object', 'arguments': json.dumps({'object_id': 'b'})},
            {'type': 'tool_call', 'id': 'call2', 'name': 'search_objects',
             'arguments': json.dumps({'query': '', 'allowed_ids': ['b']})}],
            [{'type': 'text', 'text': '此对象不在本次范围内。'}]])
        result, _ = self.start(sid, provider)
        final = self.wait(result['run']['id'])
        self.assertEqual(final['run']['allowed_ids'], ['a'])
        self.assertEqual(final['run']['status'], 'succeeded')
        results = [json.loads(m['content']) for m in provider.calls[1] if m['role'] == 'tool']
        self.assertEqual(len(results), 2)
        self.assertTrue(all('error' in item for item in results))
        self.assertNotIn('Private', json.dumps(provider.calls, ensure_ascii=False))
        self.assertTrue(all(not e['ok'] for e in final['events'] if e['type'] == 'tool_finished'))


if __name__ == '__main__':
    unittest.main()
