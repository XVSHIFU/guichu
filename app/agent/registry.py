"""One bounded tool registry; confirmation APIs are intentionally absent."""
import json
import time
import directory_sizes
from . import actions,context

def schema(name,description,fields):
    return {'type':'function','function':{'name':name,'description':description,'strict':True,'parameters':{'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}}}
STRING={'type':'string'}
EXTRA=[schema('load_skill','读取已启用内置技能正文，不能传文件路径',{'skill_id':{'type':'string','enum':list(context.SKILLS)}}),
       schema('inspect_config','实时检查 Codex MCP enabled 或 Claude 用户 MCP 注册状态，只返回脱敏字段',{'object_id':STRING}),
       schema('measure_directory','按需统计已授权目录，最多15秒；未完成结果不等于完整大小',{'object_id':STRING}),
       schema('get_action_capabilities','查询对象实际支持的提案动作',{'object_id':STRING}),
       schema('propose_change','创建需用户卡片确认的提案，不执行修改。parameters中不用的字段填null。',{'object_id':STRING,'action':{'type':'string','enum':['retention','mcp_enabled','claude_mcp_remove','batch_category']},'parameters':{'type':'object','properties':{'decision':{'type':['string','null'],'enum':['未标记','保留','待确认',None]},'enabled':{'type':['boolean','null']},'changes':{'type':['array','null'],'items':{'type':'object','properties':{'object_id':STRING,'category':{'type':['string','null']}},'required':['object_id','category'],'additionalProperties':False}}},'required':['decision','enabled','changes'],'additionalProperties':False}}),
       schema('get_action_status','查询本会话提案执行状态',{'proposal_id':STRING}),
       schema('propose_restore','预览恢复本会话已执行提案，仍需用户确认',{'object_id':STRING,'proposal_id':STRING})]

class Registry:
    def __init__(self,connection,run,objects,relations,base,action_context,cancel,deadline):
        self.connection,self.run,self.objects,self.relations,self.base=connection,run,objects,relations,base
        self.context=action_context or {};self.cancel=cancel;self.deadline=deadline
        self.mcp=self.context.get('mcp_registry')
    def tools_catalog(self):return self.base.tools_catalog()+EXTRA+(self.mcp.tools_catalog() if self.mcp else [])
    def execute(self,name,args,call_id):
        if self.cancel.is_set():raise InterruptedError()
        if time.monotonic()>self.deadline:raise TimeoutError()
        if not isinstance(args,dict):return {'error':{'code':'invalid_arguments','message':'参数必须是对象'}}
        if name=='load_skill':
            if set(args)!={'skill_id'} or not isinstance(args.get('skill_id'),str) or args['skill_id'] not in context.SKILLS:return {'error':{'code':'unknown_skill','message':'技能未启用'}}
            return context.load_skill(args['skill_id'])
        if name=='get_action_status':
            if set(args)!={'proposal_id'} or not isinstance(args['proposal_id'],str):return {'error':{'code':'invalid_arguments','message':'提案ID无效'}}
            with self.connection() as db:
                row=db.execute('SELECT payload FROM agent_proposals WHERE id=? AND session_id=?',(args['proposal_id'],self.run['session_id'])).fetchone()
            return {'proposal':json.loads(row[0])} if row else {'error':{'code':'not_found','message':'本会话无此提案'}}
        if name in {'measure_directory','inspect_config'}:
            if set(args)!={'object_id'} or not isinstance(args['object_id'],str):return {'error':{'code':'invalid_arguments','message':'对象参数无效'}}
            obj=next((o for o in self.objects if o['id']==args['object_id'] and o['id'] in self.run['allowed_ids']),None)
            if not obj:return {'error':{'code':'scope','message':'对象不在本次范围内'}}
            if name=='inspect_config':
                supported=actions.capabilities(obj,self.context)['actions']
                if not {'mcp_enabled','claude_mcp_remove'} & set(supported):return {'error':{'code':'unsupported','message':'此对象不支持实时配置检查'}}
                try:
                    import mcp_config_action,claude_config_action
                    claude='claude_mcp_remove' in supported
                    preview=(claude_config_action if claude else mcp_config_action).preview(self.context['claude_config_path' if claude else 'config_path'],obj['name'],False)
                    return {'object_id':obj['id'],'registered':True,**({} if claude else {'enabled':preview['before_enabled']}),'hash':preview['before_hash'],'connection':'未实测','source':'实时解析受支持配置'}
                except Exception:return {'error':{'code':'unavailable','message':'配置无法安全解析，未读取或返回正文'}}
            if obj.get('kind')!='directory':return {'error':{'code':'not_directory','message':'此对象不是目录'}}
            result,status=directory_sizes.dispatch(self.connection,'/api/size/start',{'path':obj.get('path'),'request_id':'agent-'+call_id})
            if status not in {200,202}:return {'error':{'code':'measurement_unavailable','message':result.get('error','无法统计')}}
            task=result['task'];until=min(self.deadline,time.monotonic()+15)
            while task['status'] not in directory_sizes.TERMINAL:
                if self.cancel.is_set() or time.monotonic()>=until:
                    directory_sizes.dispatch(self.connection,'/api/size/cancel',{'id':task['id']})
                    if self.cancel.is_set():raise InterruptedError()
                    return {'task_id':task['id'],'partial':True,'observed_bytes':task['bytes'],'error':{'code':'budget','message':'统计达到本次时间预算，已请求停止；已观察大小不代表完整目录'}}
                self.cancel.wait(.05)
                task=directory_sizes.dispatch(self.connection,'/api/size/get',{'id':task['id']})[0]['task']
            return {'task_id':task['id'],'status':task['status'],'bytes':task['bytes'],'files':task['files'],'directories':task['directories'],'errors':task['errors'],'partial':task['status']!='succeeded','checked_at':task['updated_at']}
        if name in {'get_action_capabilities','propose_change','propose_restore'}:
            fields={'get_action_capabilities':{'object_id'},'propose_change':{'object_id','action','parameters'},'propose_restore':{'object_id','proposal_id'}}[name]
            if set(args)!=fields or not isinstance(args.get('object_id'),str):return {'error':{'code':'invalid_arguments','message':'参数无效'}}
            obj=next((o for o in self.objects if o['id']==args['object_id'] and o['id'] in self.run['allowed_ids']),None)
            if not obj and name!='propose_restore':return {'error':{'code':'scope','message':'对象不在本次范围内'}}
            if name=='get_action_capabilities':return actions.capabilities(obj,self.context)
            if isinstance(args.get('parameters'),dict):
                if set(args['parameters'])-{'decision','enabled','changes'}:return {'error':{'code':'invalid_arguments','message':'不接受额外修改字段'}}
                args={**args,'parameters':{k:v for k,v in args['parameters'].items() if v is not None}}
            return actions.propose(self.connection,self.run,args,self.objects,self.context,call_id,name=='propose_restore')
        if self.mcp and name.startswith('mcp_'):
            return self.mcp.execute_tool(name,args,cancel=self.cancel,deadline=self.deadline)
        return self.base.execute_tool(name,args,self.objects,self.relations,self.run['allowed_ids'])
