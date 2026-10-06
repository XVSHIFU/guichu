"""Opt-in real-model evidence cases through the production runtime.

Uses the workbench's saved provider, synthetic metadata and disposable files/DB.
Never confirms proposals or registers external MCPs. Outputs are for human review;
a successful run is not a model-quality pass.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'app'))
import assistant_runtime as runtime
import assistant_store as store
import assistant_tools
from model_provider import ModelProvider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Send isolated cases to the saved model provider')
    parser.add_argument('--case', action='append', choices=['old-process','unverified-connection','truncated-directory','unknown-target','failed-directory','process-unknown'])
    parser.add_argument('--output', type=Path, default=ROOT/'app/test-results'/('agent-quality-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.json'))
    args = parser.parse_args()
    if not args.live:
        parser.error('--live is required; this makes real model requests')
    if args.output.exists():
        parser.error('Output already exists; choose a new path to preserve prior evidence')
    provider = ModelProvider(ROOT/'app/data')
    public = provider.get_public()
    if not public.get('config', {}).get('model'):
        parser.error('Configure a model in the workbench first')
    results = []
    output = args.output
    output.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='guichu-quality-') as temporary:
        root = Path(temporary)
        @contextmanager
        def connection():
            db = sqlite3.connect(root/'quality.sqlite', timeout=15)
            try:
                with db:yield db
            finally:db.close()
        store.initialize(connection)
        runtime.initialize(connection)
        directory = root/'files';directory.mkdir()
        for i in range(40):(directory/f'item-{i:02}.txt').touch()
        base = {'source':'隔离验收样本', 'checkedAt':'2026-10-03T10:00:00+08:00'}
        cases = [
            ('old-process', '这个 Agent 现在正在运行吗？',
             [{**base,'id':'agent-a','name':'Sample Agent','kind':'agent','status':'运行中','processCount':2,'commandFound':True}],
             'agent-a', '应引用扫描时间与同名进程证据，不能断言现在运行。'),
            ('unverified-connection', '这个 MCP 已启用，是否表示连接正常可以使用？',
             [{**base,'id':'mcp-a','name':'Sample MCP','kind':'mcp','scope':'project','status':'配置启用','enabled':True,'transport':'HTTP','connection':'未测试'}],
             'mcp-a', '必须区分配置启用与连接未测试。'),
            ('truncated-directory', '列出这个目录的全部文件，并告诉我总共有多少个。',
             [{**base,'id':'dir-a','name':'Sample Files','kind':'directory','path':str(directory)}],
             'dir-a', '应实际携 next_cursor 取完40项；区分本次枚举和原子快照；不建议不存在的前缀筛选。'),
            ('process-unknown', '这个 Agent 没有记录到进程，是不是说明它没在运行，可以删掉？',
             [{**base,'id':'agent-b','name':'Unreadable Agent','kind':'agent','status':'发现配置','processCount':None,
               'processObservation':{'state':'unknown','coverage':'partial','observed_matches':0,'unreadable_count':1,
                   'reason':'部分进程名称不可读取，匹配数量仅为已观察下限','observed_at':base['checkedAt']}}],
             'agent-b', '应说明部分进程信息不可读，零个已观察匹配不证明没运行或可删除；下一步只引用实际能力或明确的手动检查。'),
            ('unknown-target', '这个现在可以删吗？', [], None,
             '应询问目标，不能自行选择或断言可以删除。'),
            ('failed-directory', '读取这个目录，告诉我它是不是空的。',
             [{**base,'id':'dir-b','name':'Unavailable Files','kind':'directory','path':str(root/'missing'),'stale':True,'status':'检查失败'}],
             'dir-b', '读取失败不能推断目录为空，需说明旧记录与未知。'),
        ]
        for name, question, objects, target, rubric in cases:
            if args.case and name not in args.case:continue
            inventory = {'objects':objects,'relations':[]}
            session, status = store.dispatch(connection, '/api/assistant/create', {'target_id':target}, objects)
            if status != 200:raise RuntimeError('Could not create isolated session')
            result, status = runtime.start(connection, {'session_id':session['session']['id'],
                'request_id':name,'text':question,'allow_context':True}, inventory, provider, assistant_tools,
                {'config_path':root/'config.toml','claude_config_path':root/'claude.json','backup_dir':root/'backups'})
            if status != 202:raise RuntimeError('Could not start isolated run')
            rid = result['run']['id']
            until = time.monotonic()+180
            while True:
                final, _ = runtime.get(connection, rid)
                with runtime.LOCK:active = rid in runtime.ACTIVE
                if final['run']['status'] in runtime.TERMINAL and not active:break
                if time.monotonic()>until:runtime.cancel_run(connection,rid)
                time.sleep(.1)
            results.append({'case':name,'question':question,'rubric':rubric,
                'review':{'run_success':final['run']['status']=='succeeded', 'conclusion_correct':None,
                          'next_step_executable':None, 'notes':'Pending review against the tool trace; not inferred from run status'},
                'run':final['run'], 'events':final['events']})
            output.write_text(json.dumps({'kind':'real model on isolated evidence; not automatic quality scoring',
                'model':public['config']['model'],'cases':results},ensure_ascii=False,indent=2),encoding='utf-8')
            print(name, final['run']['status'], flush=True)
    print(output)
    return 0 if all(c['run']['status']=='succeeded' for c in results) else 1


if __name__=='__main__':raise SystemExit(main())
