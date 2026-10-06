"""Conservative provenance; discovery source is not acquisition history."""
CHANNELS = ['未知', 'Microsoft Store', 'winget', 'Scoop', 'Chocolatey', 'npm', 'pnpm', 'Yarn', 'pip', 'pipx', 'uv', 'Conda', '手动安装', '系统预装', '其他']
METHODS = ['未知', '安装包', 'MSI', 'MSIX / AppX', '便携版', '包管理器', '源码构建']
DOWNLOADS = ['未知', 'Microsoft Store', 'GitHub Releases', '软件官网', '包仓库', '其他网站', '本地 / 离线文件']
OPTIONS = {'channel': CHANNELS, 'method': METHODS, 'download': DOWNLOADS}


def valid_override(value):
    return isinstance(value, dict) and all(k in OPTIONS and isinstance(v, str) and v in OPTIONS[k] for k, v in value.items())


def enrich(obj, override=None):
    if obj.get('kind') not in ('software', 'agent'):
        return
    origin = {'channel': '未知', 'method': '未知', 'download': '未知', 'evidence': []}
    if obj.get('packageFamily'):
        origin['method']='MSIX / AppX'
        origin['evidence'].append('Windows 当前用户应用登记：'+obj['packageFamily'])
        if obj.get('packageSignature')=='Store':
            origin['channel']='Microsoft Store'
            origin['evidence'].append('Microsoft Store 签名包；不代表最初下载页面已知')
        elif obj.get('packageSignature')=='System':
            origin['channel']='系统预装'
            origin['evidence'].append('Windows System 签名包')
    if obj.get('registryKey'):
        origin['method'] = 'MSI' if obj.get('windowsInstaller') else '安装包'
        origin['evidence'].append('Windows 软件登记记录；不包含原始下载来源')
    if obj.get('distribution') in ('npm', 'pip'):
        origin['method'] = '包管理器'
        origin['evidence'].append('已发现 ' + ('Node.js' if obj['distribution'] == 'npm' else 'Python') + ' 包元数据')
    installer = obj.get('packageInstaller')
    if installer in ('npm', 'pnpm', 'yarn', 'pip', 'pipx', 'uv', 'conda'):
        origin['channel'] = {'yarn': 'Yarn', 'conda': 'Conda'}.get(installer, installer)
        origin['evidence'].append('安装元数据记录的安装器：' + installer)
    channel=obj.get('managedChannel')
    if channel in CHANNELS and channel!='未知':
        origin['channel']=channel
        if channel not in ('winget','Microsoft Store'):origin['method']='包管理器'
        origin['evidence'].append(obj.get('managerBasis') or (channel+' 本地安装记录：'+obj.get('managerReceipt','')))
    if obj.get('wingetPackageId'):
        origin['channel']='winget'
        origin['evidence'].append('卸载登记包含 WinGetPackageIdentifier：'+obj['wingetPackageId'])
    if obj.get('managedDownload') in DOWNLOADS and obj['managedDownload']!='未知':
        origin['download']=obj['managedDownload']
        origin['evidence'].append('已安装包附带的下载记录；不保存完整下载 URL')
    # Old snapshots and unproven homepage/catalog matches intentionally stay unknown.
    obj['detectedOrigin'] = dict(origin)
    if override:
        origin.update({k: v for k, v in override.items() if k in OPTIONS and v in OPTIONS[k]})
    origin['manualFields'] = list(override or {})
    obj['softwareOrigin'] = origin
