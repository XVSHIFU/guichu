"""Keep failed-source evidence without hiding successful-source removals."""
from pathlib import Path

def reconcile(previous,current):
    sources={s['id']:s for s in current.get('sources',[])}
    failed={s['id'] for s in current.get('sources',[]) if s['status']!='success'}
    if not failed:return current
    result={**current,'objects':[dict(o) for o in current['objects']],'relations':list(current.get('relations',[]))}
    present={o['id'] for o in result['objects']}
    retained=set()
    previous_objects={o['id']:o for o in previous.get('objects',[])}
    for obj in previous.get('objects',[]):
        key=obj.get('sourceKey')
        dependencies=list(obj.get('sourceDependencies',[]))
        # Older collectors accidentally stored a skill display label as the
        # source group, including on MCPs collected after the skill loop.
        if obj['kind'] in ['skill','mcp'] and key not in {'environment','agent-config','software-registry','icons','disks'} and not str(key).startswith(('registered:', 'agent-config:')):
            key='agent-config'
        if obj['kind'] in ('mcp','plugin','skill') and key=='agent-config' and obj.get('path'):
            from inventory import config_source
            specific=config_source(Path(obj['path']).parent.parent if obj['kind']=='skill' else obj['path'])
            if obj['kind']=='plugin':specific+=':plugins'
            if obj['kind']=='skill':
                for edge in previous.get('relations',[]):
                    parent=previous_objects.get(edge.get('from'),{})
                    if edge.get('to')==obj['id'] and parent.get('kind')=='plugin' and parent.get('path'):
                        dependencies.append(config_source(parent['path'])+':plugins')
            if specific in sources or dependencies:
                key=specific
        if key is None:key='software-registry' if obj['kind']=='software' else 'agent-config' if obj['kind'] in ['skill','plugin','mcp'] else 'environment'
        source=sources.get(key,{})
        failed_object=key in failed and ('retainObjectIds' not in source or obj['id'] in source['retainObjectIds'])
        failed_dependency=key not in sources and any(dep in failed for dep in dependencies)
        if (failed_object or failed_dependency) and obj['id'] not in present:
            result['objects'].append({**obj,'sourceKey':key,'sourceDependencies':dependencies,'stale':True,'status':'检查失败'})
            retained.add(obj['id']);present.add(obj['id'])
    for edge in previous.get('relations',[]):
        if (edge['from'] in retained or edge['to'] in retained) and edge['from'] in present and edge['to'] in present and edge not in result['relations']:result['relations'].append(edge)
    return result
