"""Current-user packaged applications. Never launches discovered applications."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

SCRIPT = r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$apps=@(Get-StartApps | Select-Object Name,AppID)
$packages=@(Get-AppxPackage -PackageTypeFilter Main | ForEach-Object {
 [pscustomobject]@{Name=$_.Name;Family=$_.PackageFamilyName;Version=$_.Version.ToString();Path=$_.InstallLocation;Signature=$_.SignatureKind.ToString();Publisher=$_.Publisher;NonRemovable=[bool]$_.NonRemovable}
})
@{packages=$packages;apps=$apps}|ConvertTo-Json -Depth 4 -Compress
'''


def from_metadata(payload, at):
    objects=[]
    packages, apps=payload['packages'],payload['apps']
    if not isinstance(packages,list) or not isinstance(apps,list):raise ValueError('invalid package inventory')
    for package in packages:
        family=package.get('Family')
        if not isinstance(family,str) or not family:raise ValueError('missing package family')
        entries=[{'name':a['Name'],'appId':a['AppID']} for a in apps if isinstance(a.get('AppID'),str) and a['AppID'].startswith(family+'!') and isinstance(a.get('Name'),str)]
        # Keep package identity distinct from possibly stale/localized Start menu names.
        name=package['Name']
        known={'OpenAI.Codex':'Codex','OpenAI.ChatGPT':'ChatGPT'}
        title=known.get(name) or (entries[0]['name'] if entries else name)
        objects.append({'id':'software:appx:'+hashlib.sha256(family.casefold().encode()).hexdigest()[:16],
            'kind':'software','name':title,'appxName':name,'packageFamily':family,
            'version':package.get('Version',''),'path':package.get('Path',''),'installPath':package.get('Path',''),
            'vendor':package.get('Publisher',''),'packageSignature':package.get('Signature',''),
            'nonRemovable':package.get('NonRemovable') is True,
            'applicationEntries':entries,'interfaces':['桌面应用'],'installationForm':'桌面应用',
            'source':'Windows 应用登记','sourceKey':'windows-appx','checkedAt':at,'status':'已登记',
            'description':'Windows 登记的桌面应用。'+('开始菜单：'+'、'.join(e['name'] for e in entries)+'。' if entries else '')})
    return objects


def collect_windows_apps(at):
    result={'objects':[],'relations':[],'issues':[],'sources':[{'id':'windows-appx','status':'success','checkedAt':at}]}
    if os.name!='nt':return result
    try:
        powershell=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
        process=subprocess.run([str(powershell),'-NoProfile','-NonInteractive','-Command',SCRIPT],capture_output=True,timeout=35,creationflags=subprocess.CREATE_NO_WINDOW)
        if process.returncode or len(process.stdout)>8*1024*1024:raise ValueError('package query failed')
        result['objects']=from_metadata(json.loads(process.stdout.decode('utf-8-sig')),at)
    except (OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired):
        result['sources'][0]['status']='failed'
        result['issues'].append({'sourceKey':'windows-appx','name':'Windows 应用','reason':'应用登记读取失败，保留上次记录'})
    return result
