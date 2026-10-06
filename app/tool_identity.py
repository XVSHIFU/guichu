"""Evidence-based presentation labels; never grants execution capabilities."""
import ntpath
import re

PRODUCTS = {
    'codex': ('Codex', {'codex'}, {'@openai/codex'}),
    'claude': ('Claude Code', {'claude', 'claude code'}, {'@anthropic-ai/claude-code'}),
    'pi': ('pi', set(), {'@mariozechner/pi-coding-agent', '@earendil-works/pi-coding-agent'}),
    'dsh': ('DeepSeek Harness', {'deepseek harness', 'deepseek-harness'}, {'@deepseek-ai/dsh'}),
}
HELPER = re.compile(r'^(uninstall(?:er)?(?:\b|_)|unins\d*|update(?:r)?(?:\b|_)|crashpad_handler$|crashreporter$|notification_helper$)', re.I)


def enrich(data):
    tools = [o for o in data['objects'] if o['kind'] in ('software', 'agent')]
    for obj in tools:
        obj.pop('installationId', None)
        name = obj.get('name', '').casefold()
        obj['installationForm'] = obj.get('installationForm','') if obj.get('managerRecord') else '桌面应用' if obj.get('packageFamily') else '命令行' if obj.get('distribution') or (obj['kind']=='agent' and obj.get('commandFound')) else '配置' if obj['kind']=='agent' else ''
        stem = ntpath.splitext(ntpath.basename(obj.get('executable') or obj.get('path', '')))[0].casefold()
        helper = bool(obj.get('portable') and HELPER.search(stem))
        obj['entryRole'] = 'auxiliary' if helper else 'primary'
        obj['capabilities'] = ['software']
        obj['agentIdentity'] = 'unknown'
        obj['identityEvidence'] = '未匹配已知 Agent 产品规则；不代表它没有 Agent 能力。'
        if obj['kind'] == 'agent' and name not in ('ccswitch', 'herdr'):
            obj['capabilities'].append('agent')
            obj['agentIdentity'] = 'recognized'
            obj['identityEvidence'] = '已有产品适配器识别到配置或命令入口；不代表正在运行。'
        for product, (title, names, packages) in PRODUCTS.items():
            if not helper and (name in names or stem in names or obj.get('packageName') in packages):
                obj['productId'] = product
                if obj.get('packageName'): obj['name'] = title
                obj['capabilities'] = ['software', 'agent']
                obj['agentIdentity'] = 'recognized'
                obj['identityEvidence'] = '已知产品名称或包标识匹配；未验证发布者签名、运行状态或连接。'
                if not obj.get('description'):
                    obj['description'] = title + ' 的本地入口，可用于 AI 辅助任务。'
                break
        if obj.get('packageName') == '@deepseek-ai/dsh':
            obj['interfaces'] = ['终端', '本地网页']
            obj['description'] = 'DeepSeek Harness 命令包，提供 dsh web 本地网页入口。未启动服务，网页地址和运行状态未验证。'
        location = obj.get('installPath') or obj.get('executable') or (obj.get('path') if obj['kind'] == 'software' else '') or ''
        drive = ntpath.splitdrive(location)[0]
        obj['installDrive'] = drive.upper() if re.fullmatch('[a-zA-Z]:', drive) else '位置待确认'
        obj['installPath'] = location
        if helper:
            obj['description'] = '卸载、更新或软件附属程序，不作为独立主程序展示；可在软件附属程序筛选中查看。'
    # A known configuration and a package in the same command prefix represent
    # one installation. Keep IDs/relations for actions, show its package once.
    for config in (o for o in tools if o['kind'] == 'agent' and o.get('executable')):
        command = ntpath.splitext(ntpath.basename(config['executable']))[0].casefold()
        prefix = ntpath.dirname(config['executable']).casefold()
        for package in (o for o in tools if o.get('distribution') == 'npm'):
            if command in package.get('commands', []) and ntpath.dirname(package['installPath']).casefold() == prefix:
                config['installationId'] = package['id']
                edge = {'from': package['id'], 'to': config['id'], 'label': '配置与能力'}
                if edge not in data['relations']: data['relations'].append(edge)
                break
    # Only attach helpers when a single main entry exists in the same directory.
    for product in PRODUCTS:
        instances=[o for o in tools if o.get('productId')==product and not o.get('installationId') and not o.get('duplicateOf')]
        for i,instance in enumerate(instances):
            for other in instances[i+1:]:
                edge={'from':instance['id'],'to':other['id'],'label':'同一产品的其他安装'}
                if edge not in data['relations']:data['relations'].append(edge)
    for helper in (o for o in tools if o['entryRole'] == 'auxiliary'):
        parent = ntpath.dirname(helper.get('path', '')).casefold()
        mains = [o for o in tools if o['entryRole'] == 'primary' and o.get('portable') and ntpath.dirname(o.get('path', '')).casefold() == parent]
        if len(mains) == 1:
            edge = {'from': mains[0]['id'], 'to': helper['id'], 'label': '软件附属程序'}
            if edge not in data['relations']: data['relations'].append(edge)
    return data
