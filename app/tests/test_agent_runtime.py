import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_assistant_runtime import AssistantRuntimeTests,FakeProvider
import assistant_runtime as runtime
import assistant_tools as tools
from agent import actions,context
from agent.registry import Registry

def call(name,args):return {'type':'tool_call','id':'provider-call','name':name,'arguments':json.dumps(args)}

class AgentRuntimeTests(AssistantRuntimeTests):
    def setUp(self):
        super().setUp()
        self.config=Path(self.temp.name)/'config.toml'
        self.original=b'[mcp_servers.sample]\ncommand="fixture"\nenabled=true\n[mcp_servers.sample.env]\nAPI_KEY="private-fixture"\n'
        self.config.write_bytes(self.original)
        self.inventory['objects'][0].update(name='sample',scope='codex',source='用户配置',path=str(self.config))
        self.context={'config_path':self.config,'backup_dir':Path(self.temp.name)/'backups','preferences':{'instructions':'简洁回答'}}
        with self.connection() as db:db.execute('CREATE TABLE notes(id TEXT PRIMARY KEY,decision TEXT,body TEXT,updated TEXT)')

    def agent_start(self,sid,provider,key='new',text='停用当前 MCP'):
        self.providers.append(provider)
        result,status=runtime.start(self.connection,{'session_id':sid,'request_id':key,'text':text,'allow_context':True},self.inventory,provider,tools,self.context)
        self.assertEqual(status,202);self.runs.append(result['run']['id']);return self.wait(result['run']['id'])

    def proposal(self,sid,key='new'):
        final=self.agent_start(sid,FakeProvider([[call('propose_change',{'object_id':'a','action':'mcp_enabled','parameters':{'enabled':False,'decision':None}})]]),key)
        self.assertEqual(final['run']['status'],'awaiting_confirmation')
        return final['run']['proposals'][0],final

    def confirm(self,p,sid=None):
        return runtime.confirm_proposal(self.connection,{'session_id':sid or p['session_id'],'proposal_id':p['id'],'revision':1,'request_id':'confirm'},self.inventory,action_context=self.context)

    def test_budget_exhaustion_preserves_results_and_reserves_summary(self):
        provider=FakeProvider([[dict(call('get_object',{'object_id':'a'}),id=f'call-{i}') for i in range(8)],[{'type':'text','text':'已检查部分配置，其余尚未检查。'}]])
        provider.get_public=lambda: {'config':{'model':'fake','timeout':10,'max_tool_calls':6,'max_requests':4}}
        final=self.agent_start(self.session()['id'],provider,text='检查配置')
        self.assertEqual(final['run']['status'],'succeeded')
        self.assertEqual(len([e for e in final['events'] if e['type']=='tool_started']),6)
        self.assertEqual(len([e for e in final['events'] if e['type']=='tool_skipped']),2)
        results=[m for m in provider.calls[-1] if m['role']=='tool']
        self.assertEqual(len(results),8)
        self.assertIn('budget_exhausted',results[-1]['content'])
        self.assertEqual(final['run']['answer'],'已检查部分配置，其余尚未检查。')

    def test_settings_budget_allows_32_and_zero_disables_tools(self):
        class BudgetProvider(FakeProvider):
            def get_public(self):return {'config':{'model':'fake','timeout':10,'max_tool_calls':32,'max_requests':12}}
        provider=BudgetProvider([[dict(call('get_object',{'object_id':'a'}),id=str(i)) for i in range(32)],[{'type':'text','text':'完成'}]])
        with patch.object(tools,'execute_tool',wraps=tools.execute_tool) as execute:
            final=self.agent_start(self.session()['id'],provider,text='检查配置')
        self.assertEqual(final['run']['status'],'succeeded')
        self.assertEqual(final['run']['budget']['max_requests'],12)
        self.assertEqual(len([e for e in final['events'] if e['type']=='tool_started']),32)
        self.assertEqual(execute.call_count,1)
        self.assertEqual(len([e for e in final['events'] if e.get('cached')]),31)
        class ZeroProvider(FakeProvider):
            def get_public(self):return {'config':{'model':'fake','timeout':10,'max_tool_calls':0,'max_requests':1}}
            def stream_completion(self,messages,catalog,cancel,deadline):
                self.catalog=catalog
                yield {'type':'text','text':'本轮工具已禁用，无法检查。'}
        zero=ZeroProvider()
        final=self.agent_start(self.session()['id'],zero,text='检查配置')
        self.assertEqual(zero.catalog,[])
        self.assertEqual(final['run']['status'],'succeeded')

    def test_requests_above_old_eight_round_limit_finish(self):
        provider=FakeProvider([[dict(call('get_object',{'object_id':'a'}),id=str(i))] for i in range(10)]+[[{'type':'text','text':'完成十轮查询'}]])
        provider.get_public=lambda: {'config':{'model':'fake','timeout':15,'max_tool_calls':32,'max_requests':12}}
        final=self.agent_start(self.session()['id'],provider,text='检查配置')
        self.assertEqual(final['run']['status'],'succeeded')
        self.assertEqual(len(provider.calls),11)
        self.assertEqual(final['run']['answer'],'完成十轮查询')

    def test_semantic_memory_is_persisted_counted_and_used(self):
        sid=self.session()['id']
        with self.connection() as db:
            session=json.loads(db.execute('SELECT payload FROM assistant_sessions WHERE id=?',(sid,)).fetchone()[0])
            session['messages']=[{'id':str(i),'role':'user' if i%2==0 else 'assistant','text':'历史任务'+str(i),'mode':'readonly'} for i in range(16)]
            db.execute('UPDATE assistant_sessions SET payload=? WHERE id=?',(json.dumps(session),sid))
        summary={'goals':['检查MCP'],'decisions':['仅检查'],'unfinished':['验证连接'],'evidence':['扫描对象a'],'uncertainties':[]}
        provider=FakeProvider([[{'type':'text','text':json.dumps(summary)},{'type':'usage','usage':{'total_tokens':9}},{'type':'done','finish_reason':'stop'}],[{'type':'text','text':'继续检查。'},{'type':'usage','usage':{'total_tokens':4}}]])
        provider.get_public=lambda: {'config':{'model':'fake','timeout':60,'max_tool_calls':16,'max_requests':3}}
        final=self.agent_start(sid,provider,text='继续')
        self.assertEqual(final['run']['status'],'succeeded')
        self.assertEqual(final['run']['memory_requests'],1)
        self.assertEqual(final['run']['memory_status'],'compressed')
        self.assertEqual(final['run']['usage']['total_tokens'],13)
        self.assertIn('仅检查',json.dumps(provider.calls[1],ensure_ascii=False))
        follow=FakeProvider([[{'type':'text','text':'继续。'}]])
        final=self.agent_start(sid,follow,key='next',text='继续')
        self.assertEqual(final['run']['memory_requests'],0)
        self.assertEqual(final['run']['memory_status'],'cached')
        import assistant_store
        self.runs.clear()  # Session deletion intentionally removes its run journals.
        assistant_store.dispatch(self.connection,'/api/assistant/delete',{'id':sid},self.inventory['objects'])
        with self.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM agent_memory').fetchone()[0],0)

    def test_greeting_context_omits_inventory_and_no_implicit_tool_calls(self):
        provider=FakeProvider([[{'type':'text','text':'你好！'}]])
        with patch.object(tools,'execute_tool',wraps=tools.execute_tool) as executed:
            final=self.agent_start(self.session()['id'],provider,text='你好')
        self.assertEqual(executed.call_count,0)
        self.assertNotIn('Private',json.dumps(provider.calls))
        self.assertNotIn('private-fixture',json.dumps(provider.calls))
        self.assertEqual(final['run']['answer'],'你好！')
        self.assertIn('简洁回答',json.dumps(provider.calls,ensure_ascii=False))

    def test_real_toml_proposal_confirm_duplicate_receipt_and_restore(self):
        sid=self.session()['id'];p,final=self.proposal(sid)
        self.assertEqual(self.config.read_bytes(),self.original)
        self.assertEqual(self.session(sid)['messages'][-1]['proposals'][0]['id'],p['id'])
        self.assertEqual(self.confirm(p,self.session()['id'])[1],404)
        result,status=self.confirm(p);self.assertEqual(status,200);self.assertEqual(result['proposal']['state'],'applied')
        self.assertIn(b'enabled=false',self.config.read_bytes())
        count=len(result['session']['messages'])
        self.assertEqual(len(self.confirm(p)[0]['session']['messages']),count)
        self.assertEqual(len(list((Path(self.temp.name)/'backups').iterdir())),1)
        restored=self.agent_start(sid,FakeProvider([[call('propose_restore',{'object_id':'a','proposal_id':p['id']})]]),'restore')
        rp=restored['run']['proposals'][0]
        self.assertEqual(rp['operation'],'restore')
        self.assertEqual(self.confirm(rp)[0]['proposal']['state'],'restored')
        self.assertEqual(self.config.read_bytes(),self.original)
        self.assertNotIn('private-fixture',json.dumps(final,ensure_ascii=False))

    def test_conflict_reject_and_restart_never_replay(self):
        sid=self.session()['id'];p,_=self.proposal(sid)
        changed=self.original+b'\n# externally changed\n';self.config.write_bytes(changed)
        self.assertEqual(self.confirm(p)[1],409);self.assertEqual(self.config.read_bytes(),changed)
        p,_=self.proposal(sid,'second')
        self.assertEqual(runtime.reject_proposal(self.connection,{'session_id':sid,'proposal_id':p['id'],'revision':1})[0]['proposal']['state'],'rejected')
        self.assertEqual(self.config.read_bytes(),changed)
        p,_=self.proposal(sid,'third');runtime.initialize(self.connection)
        self.assertEqual(self.config.read_bytes(),changed)
        runtime.cancel_run(self.connection,p['run_id'])
        self.assertEqual(self.confirm(p)[0]['proposal']['state'],'rejected')
        self.assertEqual(self.config.read_bytes(),changed)

    def test_waiting_allows_new_run_and_events_have_actual_calls(self):
        sid=self.session()['id'];p,_=self.proposal(sid)
        provider=FakeProvider([[{'type':'text','text':'正在查询。'},call('load_skill',{'skill_id':'explain-environment'})],[{'type':'text','text':'最终解释。'}]])
        final=self.agent_start(sid,provider,'followup','这是什么')
        self.assertEqual(final['run']['answer'],'最终解释。');self.assertEqual(final['run']['intermediate_answer'],'正在查询。')
        self.assertEqual(final['run']['skill_versions'],{'explain-environment':context.VERSION})
        starts=[e for e in final['events'] if e['type']=='tool_started'];ends=[e for e in final['events'] if e['type']=='tool_finished']
        self.assertEqual(starts[0]['call_id'],ends[0]['call_id']);self.assertEqual(starts[0]['round_id'],1)
        self.assertEqual(ends[0]['result']['skill_id'],'explain-environment')
        self.assertEqual([e['text'] for e in final['events'] if e['type']=='final_answer'],['最终解释。'])

    def test_scope_and_disabled_tools_cannot_execute(self):
        sid=self.session()['id']
        provider=FakeProvider([[call('propose_change',{'object_id':'b','action':'mcp_enabled','parameters':{'enabled':False}}),call('execute',{'command':'evil'})],[{'type':'text','text':'范围不足。'}]])
        final=self.agent_start(sid,provider)
        self.assertEqual(final['run']['proposals'],[]);self.assertEqual(self.config.read_bytes(),self.original)
        self.assertTrue(all(not e['ok'] for e in final['events'] if e['type']=='tool_finished'))
        self.assertEqual(context.safe({'api_key':'secret','nested':{'authorization':'bearer secret'}})['api_key'],'[已隐藏]')

    def test_fixed_help_and_changes_do_not_use_model(self):
        self.assertIn('可用命令',runtime.command(self.connection,{'text':'/help'})[0]['text'])
        self.assertEqual(runtime.command(self.connection,{'text':'/changes'})[0]['navigate'],'actions')
        self.assertEqual(runtime.command(self.connection,{'text':'/inspect'})[0]['requires_model'],True)
        self.assertEqual(runtime.command(self.connection,{'text':'/shell'})[1],400)

    def test_retention_proposal_reuses_notes_journal(self):
        sid=self.session()['id']
        final=self.agent_start(sid,FakeProvider([[call('propose_change',{'object_id':'a','action':'retention','parameters':{'decision':'保留','enabled':None}})]]))
        p=final['run']['proposals'][0]
        with self.connection() as db:self.assertIsNone(db.execute('SELECT * FROM notes').fetchone())
        result,status=self.confirm(p);self.assertEqual(status,200)
        with self.connection() as db:self.assertEqual(db.execute('SELECT decision FROM notes').fetchone()[0],'保留')
        self.assertEqual(result['session']['messages'][-1]['kind'],'action_result')

    def test_greeting_cannot_be_used_to_trigger_tool(self):
        sid=self.session()['id']
        provider=FakeProvider([[call('get_object',{'object_id':'a'})],[{'type':'text','text':'你好'}]])
        with patch.object(tools,'execute_tool',wraps=tools.execute_tool) as execute:
            final=self.agent_start(sid,provider,text='你好')
        self.assertEqual(execute.call_count,0)
        self.assertFalse(next(e for e in final['events'] if e['type']=='tool_finished')['ok'])

    def test_real_directory_measurement_and_live_config_check(self):
        import directory_sizes
        directory=Path(self.temp.name)/'content';directory.mkdir();(directory/'one.txt').write_bytes(b'12345')
        self.inventory['objects'].append({'id':'dir','name':'fixture','kind':'directory','path':str(directory)})
        run={'id':'measure-run','session_id':self.session()['id'],'allowed_ids':['dir','a']}
        registry=Registry(self.connection,run,self.inventory['objects'],[],tools,self.context,threading.Event(),time.monotonic()+10)
        with patch.object(directory_sizes.psutil,'disk_partitions',return_value=[SimpleNamespace(mountpoint=directory.anchor,opts='rw')]):
            result=registry.execute('measure_directory',{'object_id':'dir'},'measurement')
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['bytes'],5);self.assertFalse(result['partial'])
        inspected=registry.execute('inspect_config',{'object_id':'a'},'inspect')
        self.assertTrue(inspected['enabled']);self.assertEqual(inspected['connection'],'未实测')
        self.assertNotIn('private-fixture',json.dumps(inspected))

    def test_resources_history_notice_and_recorded_decision_survive_budget(self):
        sid=self.session()['id'];p,_=self.proposal(sid);self.confirm(p)
        with self.connection() as db:
            session=json.loads(db.execute('SELECT payload FROM assistant_sessions WHERE id=?',(sid,)).fetchone()[0])
            session['messages'] += [{'id':str(i),'role':'user','mode':'readonly','text':'x'*2000} for i in range(20)]
            db.execute('UPDATE assistant_sessions SET payload=? WHERE id=?',(json.dumps(session),sid))
        provider=FakeProvider([[{'type':'text','text':'保留已执行记录。'}]])
        final=self.agent_start(sid,provider,'history','继续')
        self.assertTrue(final['run']['history_trimmed'])
        sent=json.dumps(provider.calls,ensure_ascii=False)
        self.assertIn(p['id'],sent);self.assertIn('applied',sent);self.assertIn('未覆盖',sent);self.assertEqual(final['run']['memory_status'],'budget_skipped')
        self.assertIn('触发：',context.load_skill('manage-capability')['instructions'])

    def test_measurement_budget_cancels_and_reports_partial(self):
        import directory_sizes
        run={'id':'r','session_id':'s','allowed_ids':['dir']}
        registry=Registry(self.connection,run,[{'id':'dir','kind':'directory','path':'C:/fixture'}],[],tools,{},threading.Event(),time.monotonic()+10)
        task={'id':'size','status':'running','bytes':12}
        with patch.object(directory_sizes,'dispatch',return_value=({'task':task},202)) as dispatch,patch('agent.registry.time.monotonic',side_effect=[0,0,20]):
            result=registry.execute('measure_directory',{'object_id':'dir'},'budget')
        self.assertTrue(result['partial']);self.assertEqual(result['error']['code'],'budget')
        self.assertEqual(dispatch.call_args.args[1],'/api/size/cancel')
