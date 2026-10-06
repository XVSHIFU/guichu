import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.context import safe_tool_result
from assistant_tools import execute_tool


class EvidenceQualityTests(unittest.TestCase):
    def test_missing_or_legacy_null_process_count_is_not_zero(self):
        for fields,state in [({},'not_checked'),({'processCount':None},'unknown'),({'processCount':0},'unknown')]:
            obj={'id':'a','name':'Agent','kind':'agent',**fields}
            result=execute_tool('get_object',{'object_id':'a'},[obj],[],['a'])
            self.assertEqual(result['process']['state'],state)
            self.assertEqual(result['process']['coverage'],'unknown')
            self.assertIn('processCount',result['observations'])

    def test_runtime_reports_secondary_truncation(self):
        result = safe_tool_result({'entries': [{'name': str(i)} for i in range(40)], 'truncated': False})
        self.assertEqual(len(result['entries']), 30)
        self.assertTrue(result['truncated'])
        self.assertIn('truncation_notice', result)

    def test_nested_and_text_limits_are_reported_without_credentials(self):
        for value in ({'summary': {'text': 'x'*2001}}, {str(i): i for i in range(41)}):
            self.assertTrue(safe_tool_result(value)['truncated'])
        result = safe_tool_result({'api_key': 'secret', 'entries': [1], 'truncated': False})
        self.assertEqual(result['api_key'], '[已隐藏]')
        self.assertFalse(result['truncated'])

    def test_search_keeps_stale_and_observation_evidence(self):
        obj = {'id':'a', 'name':'Agent', 'kind':'agent', 'checkedAt':'2026-10-03',
               'stale':True, 'processCount':2, 'commandFound':True, 'env':{'TOKEN':'SECRET'}}
        result = execute_tool('search_objects', {'query':'Agent'}, [obj], [], ['a'])
        found = result['objects'][0]
        self.assertTrue(found['stale'])
        self.assertEqual(found['observations']['processCount'], 2)
        self.assertIn('未实时验证', found['current_state'])
        self.assertNotIn('SECRET', str(result))
