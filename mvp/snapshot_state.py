"""Keep failed-source evidence without hiding successful-source removals."""
def reconcile(previous,current):
    failed={s['id'] for s in current.get('sources',[]) if s['status']!='success'}
    if not failed:return current
    result={**current,'objects':[dict(o) for o in current['objects']],'relations':list(current.get('relations',[]))}
    present={o['id'] for o in result['objects']}
    retained=set()
    for obj in previous.get('objects',[]):
        key=obj.get('sourceKey')
        # Older collectors accidentally stored a skill display label as the
        # source group, including on MCPs collected after the skill loop.
        if obj['kind'] in ['skill','mcp'] and key not in {'environment','agent-config','software-registry','icons','disks'} and not str(key).startswith('registered:'):
            key='agent-config'
        if key is None:key='software-registry' if obj['kind']=='software' else 'agent-config' if obj['kind'] in ['skill','plugin','mcp'] else 'environment'
        if key in failed and obj['id'] not in present:
            result['objects'].append({**obj,'sourceKey':key,'stale':True,'status':'检查失败'})
            retained.add(obj['id']);present.add(obj['id'])
    for edge in previous.get('relations',[]):
        if (edge['from'] in retained or edge['to'] in retained) and edge['from'] in present and edge['to'] in present and edge not in result['relations']:result['relations'].append(edge)
    return result
