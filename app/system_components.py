"""System-component presentation hints, not permission or deletion decisions."""
import ntpath
import os

KNOWN = {
    'microsoft.windows.filepicker': ('Windows 文件选择器', '用于系统文件打开与保存窗口'),
    'microsoft.windows.shellexperiencehost': ('Windows 桌面体验', '用于系统桌面界面'),
    'microsoft.windows.startmenuexperiencehost': ('Windows 开始菜单', '用于开始菜单'),
    'microsoft.aad.brokerplugin': ('Windows 账户登录组件', '用于账户登录与身份验证'),
    'microsoft.windows.sechealthui': ('Windows 安全中心', '用于系统安全状态与设置'),
    'microsoft.sechealthui': ('Windows 安全中心', '用于系统安全状态与设置'),
}

def enrich(obj):
    if obj.get('kind') not in ('software','agent'):return
    name=str(obj.get('appxName','')).casefold()
    path=ntpath.normcase(ntpath.normpath(obj.get('path') or ''))
    root=ntpath.normcase(ntpath.join(os.environ.get('SystemRoot',r'C:\Windows'),'SystemApps'))
    known=KNOWN.get(name) or next((value for key,value in KNOWN.items() if ntpath.basename(path).startswith(key+'_')),None)
    trusted=obj.get('packageSignature')=='System' or (bool(obj.get('packageFamily')) and path.startswith(root+'\\'))
    flagged=trusted or (obj.get('nonRemovable') is True and bool(obj.get('packageFamily')))
    obj['systemComponent']=bool(flagged)
    if not flagged:return
    obj['systemComponentBasis']='Windows 标记为不可移除' if obj.get('nonRemovable') is True else 'Windows 系统包签名或 SystemApps 安装位置'
    obj['systemComponentAdvice']='系统组件，移除可能影响 Windows 功能；建议保留。'
    if known:
        obj['originalName']=obj['name'];obj['name']=known[0];obj['description']=known[1]+'。'
