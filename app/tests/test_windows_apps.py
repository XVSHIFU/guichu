import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from windows_apps import from_metadata
from software_origin import enrich as origin
from tool_identity import enrich
from snapshot_state import reconcile

class WindowsAppsTests(unittest.TestCase):
    def test_package_and_menu_name_are_not_two_installations(self):
        payload={'packages':[{'Name':'OpenAI.Codex','Family':'OpenAI.Codex_pub','Version':'1','Path':r'C:\Apps\Codex','Signature':'Store'}],
                 'apps':[{'Name':'ChatGPT','AppID':'OpenAI.Codex_pub!App'}]}
        app=from_metadata(payload,'now')[0]
        self.assertEqual(app['name'],'Codex')
        self.assertEqual(app['applicationEntries'][0]['name'],'ChatGPT')
        origin(app)
        self.assertEqual(app['softwareOrigin']['channel'],'Microsoft Store')
        self.assertEqual(app['softwareOrigin']['download'],'未知')
        payload['packages'][0]['Version']='2'
        self.assertEqual(from_metadata(payload,'later')[0]['id'],app['id'])

    def test_cli_and_desktop_remain_separate(self):
        cli={'id':'cli','kind':'agent','name':'Codex','path':r'C:\Users\me\.codex','executable':r'C:\npm\codex.cmd','commandFound':True}
        desktop={'id':'desktop','kind':'software','name':'Codex','packageFamily':'OpenAI.Codex_pub','path':r'C:\Apps\Codex'}
        data=enrich({'objects':[cli,desktop],'relations':[]})
        self.assertNotIn('installationId',cli)
        self.assertNotIn('installationId',desktop)
        self.assertEqual(cli['installationForm'],'命令行')
        self.assertEqual(desktop['installationForm'],'桌面应用')
        self.assertEqual(data['relations'][0]['label'],'同一产品的其他安装')

    def test_sideloaded_package_is_not_store(self):
        app=from_metadata({'packages':[{'Name':'Example','Family':'Example_pub','Signature':'Developer'}],'apps':[]},'now')[0]
        origin(app)
        self.assertEqual(app['softwareOrigin']['channel'],'未知')

    def test_failed_scan_retains_but_successful_removal_does_not(self):
        previous={'objects':[{'id':'a','kind':'software','sourceKey':'windows-appx'}],'relations':[]}
        current={'objects':[],'relations':[],'sources':[{'id':'windows-appx','status':'failed'}]}
        self.assertTrue(reconcile(previous,current)['objects'][0]['stale'])
        current['sources'][0]['status']='success'
        self.assertFalse(reconcile(previous,current)['objects'])
