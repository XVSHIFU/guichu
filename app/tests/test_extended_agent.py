import json
import unittest
import test_agent_runtime as fixture
import assistant_store

class ExtendedAgentTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.AgentRuntimeTests();self.f.setUp()
    def tearDown(self):self.f.tearDown()

    def test_batch_chat_proposal_confirm_restore_and_scope(self):
        f=self.f
        for o in f.inventory['objects']:o['kind']='software'
        sid=assistant_store.dispatch(f.connection,'/api/assistant/create',{},f.inventory['objects'])[0]['session']['id']
        args={'object_id':'a','action':'batch_category','parameters':{'changes':[{'object_id':'a','category':'开发工具'},{'object_id':'b','category':'其他软件'}]}}
        result=f.agent_start(sid,fixture.FakeProvider([[fixture.call('propose_change',args)]]),text='给所有软件分类')
        self.assertEqual(result['run']['status'],'awaiting_confirmation')
        proposal=result['run']['proposals'][0]
        self.assertEqual(proposal['family'],'category-action')
        self.assertEqual(f.confirm(proposal)[1],200)
        restore=f.agent_start(sid,fixture.FakeProvider([[fixture.call('propose_restore',{'object_id':'a','proposal_id':proposal['id']})]]),key='restore',text='恢复刚才分类')
        self.assertEqual(restore['run']['status'],'awaiting_confirmation')
        self.assertEqual(f.confirm(restore['run']['proposals'][0])[1],200)
        with f.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM categories').fetchone()[0],0)

    def test_claude_restore_after_inventory_object_removed(self):
        f=self.f
        path=f.config.parent/'.claude.json';raw=b'{"mcpServers":{"sample":{"command":"fixture"}}}'
        path.write_bytes(raw);f.context['claude_config_path']=path
        f.inventory['objects'][0].update(scope='claude',path=str(path))
        sid=f.session()['id']
        result=f.agent_start(sid,fixture.FakeProvider([[fixture.call('propose_change',{'object_id':'a','action':'claude_mcp_remove','parameters':{'enabled':False}})]]),text='移除此 MCP 注册')
        self.assertEqual(result['run']['status'],'awaiting_confirmation')
        p=result['run']['proposals'][0];self.assertEqual(f.confirm(p)[1],200)
        f.inventory['objects']=[]
        restore=f.agent_start(sid,fixture.FakeProvider([[fixture.call('propose_restore',{'object_id':'a','proposal_id':p['id']})]]),key='restore',text='恢复刚才移除的注册')
        self.assertEqual(restore['run']['status'],'awaiting_confirmation')
        self.assertEqual(f.confirm(restore['run']['proposals'][0])[1],200)
        self.assertEqual(path.read_bytes(),raw)

if __name__=='__main__':unittest.main()
