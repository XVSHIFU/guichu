import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import directory_browser as browser
from assistant_tools import execute_tool, tools_catalog
from agent.context import safe_tool_result


class AssistantPaginationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        for i in range(65):(self.root/f'entry-{i:03}.txt').touch()
        self.objects = [{'id':'d','name':'Directory','kind':'directory','path':str(self.root)}]
        self.relations = []
        self.mounts = patch.object(browser.psutil, 'disk_partitions', return_value=[SimpleNamespace(mountpoint=self.root.anchor,opts='rw')])
        self.mounts.start()
        browser._snapshots.clear()

    def tearDown(self):
        self.mounts.stop()
        browser._snapshots.clear()
        self.temp.cleanup()

    def call(self, name='list_directory', args=None, allowed=None):
        return safe_tool_result(execute_tool(name, args or {'object_id':'d','cursor':None},
            self.objects,self.relations,allowed if allowed is not None else [o['id'] for o in self.objects]))

    def test_all_directory_pages_survive_runtime_without_gaps(self):
        first=self.call(); names=[e['name'] for e in first['entries']]; page=first
        self.assertEqual(first['observed_count'],65)
        self.assertNotIn(str(self.root),json.dumps(first))
        with patch.object(browser.os,'scandir',side_effect=AssertionError('must reuse enumeration')):
            while page['next_cursor']:
                self.assertIsInstance(page['next_cursor'],str)
                page=self.call(args={'object_id':'d','cursor':page['next_cursor']})
                self.assertEqual(page['observed_at'],first['observed_at'])
                self.assertLessEqual(len(page['entries']),20)
                names.extend(e['name'] for e in page['entries'])
        self.assertFalse(page['truncated'])
        self.assertIsNone(page['next_cursor'])
        self.assertTrue(page['enumeration_complete'])
        self.assertEqual(page['read_errors'],0)
        self.assertEqual(names,[f'entry-{i:03}.txt' for i in range(65)])

    def test_empty_directory_is_complete_with_null_terminal_cursor(self):
        empty=self.root/'empty';empty.mkdir()
        self.objects[0]['path']=str(empty)
        # Exercise the same tool -> context sanitizer -> JSON boundary that the
        # runtime sends to the provider, without a model request.
        result=json.loads(json.dumps(self.call(args={'object_id':'d','cursor':''})))
        self.assertEqual(result['entries'],[])
        self.assertEqual(result['observed_count'],0)
        self.assertIsNone(result['next_cursor'])
        self.assertFalse(result['truncated'])
        self.assertEqual(result['read_errors'],0)
        self.assertTrue(result['enumeration_complete'])
        self.assertTrue(result['observed_at'])

    def test_inventory_empty_exact_and_multi_page_terminal_contract(self):
        for count in (0,20,21):
            self.objects=[{'id':'target','name':'Target','kind':'agent'}]+[
                {'id':str(i),'name':'Match '+str(i),'kind':'skill'} for i in range(count)]
            self.relations=[{'from':'target','to':str(i)} for i in range(count)]
            for name,args,key in [('search_objects',{'query':'Match'},'objects'),
                                  ('get_relations',{'object_id':'target'},'relations')]:
                with self.subTest(tool=name,count=count):
                    cursor='';rows=[]
                    while True:
                        result=json.loads(json.dumps(self.call(name,{**args,'cursor':cursor})))
                        self.assertEqual(result['matched_count'],count)
                        rows.extend(result[key])
                        cursor=result['next_cursor']
                        if cursor is None:break
                        self.assertIsInstance(cursor,str)
                        self.assertNotEqual(cursor,'')
                        self.assertTrue(result['truncated'])
                    self.assertFalse(result['truncated'])
                    self.assertEqual(len(rows),count)

    def test_cursor_binds_object_authorization_and_is_not_a_path(self):
        self.objects.append({**self.objects[0],'id':'other'})
        first=self.call()
        self.assertEqual(self.call(args={'object_id':'other','cursor':first['next_cursor']})['error']['code'],'cursor_expired')
        self.assertIn('error',self.call(args={'object_id':'d','cursor':first['next_cursor']},allowed=[]))
        self.assertIn('error',self.call(args={'object_id':'d','path':str(self.root)}))
        self.assertIn('error',self.call(args={'object_id':'d','prefix':'entry-'}))

    def test_change_expiry_restart_and_links_invalidate_cursor(self):
        with patch.object(browser.time,'monotonic',return_value=100):first=self.call()
        with patch.object(browser.time,'monotonic',return_value=221):
            self.assertEqual(self.call(args={'object_id':'d','cursor':first['next_cursor']})['error']['code'],'cursor_expired')
        first=self.call()
        original=browser._signature(self.root)
        (self.root/'new.txt').touch()
        with patch.object(browser,'_signature',return_value=(*original[:2],original[2]+1,original[3])):
            self.assertEqual(self.call(args={'object_id':'d','cursor':first['next_cursor']})['error']['code'],'directory_changed')
        self.assertEqual(self.call()['observed_count'],66)
        with patch.object(Path,'is_junction',return_value=True):
            self.assertEqual(self.call(args={'object_id':'d','cursor':first['next_cursor']})['error']['code'],'directory_changed')
        browser._snapshots.clear()
        self.assertEqual(self.call(args={'object_id':'d','cursor':first['next_cursor']})['error']['code'],'cursor_expired')

    def test_partial_entry_read_is_not_complete_or_empty(self):
        entry=SimpleNamespace(name='unreadable',path=str(self.root/'unreadable'),is_dir=lambda **kw: (_ for _ in ()).throw(PermissionError()))
        class Entries:
            def __enter__(self):return iter([entry])
            def __exit__(self,*args):pass
        with patch.object(browser.os,'scandir',return_value=Entries()):result=self.call()
        self.assertEqual(result['entries'],[])
        self.assertEqual(result['read_errors'],1)
        self.assertFalse(result['enumeration_complete'])
        self.assertTrue(result['truncated'])
        self.assertIsNone(result['next_cursor'])

    def test_search_and_relations_continue_with_byte_budget(self):
        self.objects=[{'id':str(i),'kind':'skill','name':'长'*500,'source':'源'*500} for i in range(65)]
        self.relations=[{'from':'0','to':str(i),'label':'联'*500} for i in range(1,65)]
        for name, args, key, expected in [('search_objects',{'query':''},'objects',65),('get_relations',{'object_id':'0'},'relations',64)]:
            cursor=None;rows=[]
            while True:
                page=self.call(name,{**args,'cursor':cursor})
                self.assertLessEqual(len(json.dumps(page,ensure_ascii=False).encode()),32768)
                self.assertLessEqual(len(page[key]),20)
                rows.extend(page[key]);cursor=page['next_cursor']
                if cursor is None:break
            self.assertEqual(len(rows),expected)
            self.assertEqual(len({r.get('id',r.get('to')) for r in rows}),expected)
            self.assertFalse(page['truncated'])

    def test_inventory_cursor_rejects_changed_query_scope_and_data(self):
        self.objects=[{'id':str(i),'name':'same','kind':'skill'} for i in range(25)]
        page=self.call('search_objects',{'query':''})
        args={'query':'','cursor':page['next_cursor']}
        for changed in ({**args,'query':'same'},):
            self.assertEqual(self.call('search_objects',changed)['error']['code'],'cursor_expired')
        self.assertEqual(self.call('search_objects',args,allowed=['0'])['error']['code'],'cursor_expired')
        self.objects[-1]['name']='changed'
        self.assertEqual(self.call('search_objects',args)['error']['code'],'cursor_expired')

    def test_schema_exposes_string_cursor_without_paths(self):
        for tool in tools_catalog():
            function=tool['function'];properties=function['parameters']['properties']
            if function['name'] in ('list_directory','search_objects','get_relations'):
                self.assertEqual(properties['cursor']['type'],'string')
                self.assertIn('cursor',function['parameters']['required'])
                self.assertNotIn('path',properties)

    def test_initial_empty_cursor_and_mistaken_null_string_recovery(self):
        result=self.call(args={'object_id':'d','cursor':''})
        self.assertEqual(len(result['entries']),20)
        failure=self.call(args={'object_id':'d','cursor':'null'})
        self.assertEqual(failure['error']['code'],'cursor_expired')
        self.assertIn('空字符串',failure['error']['message'])
