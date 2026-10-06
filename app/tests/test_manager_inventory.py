import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from manager_inventory import collect_managers, npm_prefixes, download_kind
from snapshot_state import reconcile
from software_origin import enrich
from package_inventory import collect_packages

class ManagerTests(unittest.TestCase):
    def write(self,path,data):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(data) if isinstance(data,dict) else data,encoding='utf-8')

    def test_scoop_both_receipt_names_and_stable_upgrade_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'tool/current'
            self.write(p/'scoop-install.json',{'bucket':'main'})
            self.write(p/'scoop-manifest.json',{'version':'1','homepage':'https://github.com/example'})
            obj=collect_managers([('Scoop',root)])['objects'][0];enrich(obj)
            self.assertEqual(obj['softwareOrigin']['channel'],'Scoop')
            self.assertEqual(obj['softwareOrigin']['download'],'未知')
            (p/'scoop-install.json').rename(p/'install.json')
            (p/'scoop-manifest.json').unlink();self.write(p/'manifest.json',{'version':'2'})
            self.assertEqual(collect_managers([('Scoop',root)])['objects'][0]['id'],obj['id'])

    def test_chocolatey_requires_installed_package_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'tool'
            self.write(p/'tool.nuspec','<package><metadata><id>tool</id><version>1</version></metadata></package>')
            self.assertFalse(collect_managers([('Chocolatey',root)])['objects'])
            self.write(p/'tool.nupkg','package')
            self.assertEqual(collect_managers([('Chocolatey',root)])['objects'][0]['managedChannel'],'Chocolatey')

    def test_pipx_and_uv_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'tool'
            self.write(p/'pyvenv.cfg','home = python')
            self.write(p/'pipx_metadata.json',{'main_package':{'package':'tool','package_version':'2'}})
            self.write(p/'uv-receipt.toml','[tool]\nrequirements = []\n')
            for channel in ('pipx','uv'):
                obj=collect_managers([(channel,root)])['objects'][0];enrich(obj)
                self.assertEqual(obj['softwareOrigin']['channel'],channel)

    def test_node_manager_requires_matching_installed_package(self):
        for channel,marker in [('pnpm','.modules.yaml'),('Yarn','.yarn-integrity')]:
            with self.subTest(channel=channel),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                self.write(root/'package.json',{'dependencies':{'tool':'1'}})
                self.write(root/'node_modules'/marker,'{}')
                self.assertFalse(collect_managers([(channel,root)])['objects'])
                self.write(root/'node_modules/tool/package.json',{'name':'tool','version':'1','bin':{'tool':'main.js'},'packageManager':'npm@12'})
                obj=collect_managers([(channel,root)])['objects'][0]
                self.assertEqual(obj['managedChannel'],channel) # Author's packageManager isn't installation evidence.

    def test_missing_root_is_empty_but_corrupt_receipt_is_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.assertEqual(collect_managers([('Scoop',root/'absent')])['sources'][-1]['status'],'success')
            self.write(root/'tool/current/install.json','{bad')
            self.write(root/'tool/current/manifest.json',{'version':'1'})
            self.assertEqual(collect_managers([('Scoop',root)])['sources'][-1]['status'],'partial')

    def test_discovery_failure_retains_previous_managed_objects(self):
        previous={'objects':[{'id':'one','kind':'software','sourceKey':'manager:one','sourceDependencies':['manager-discovery']}],'relations':[]}
        with patch('manager_inventory.manager_roots',side_effect=PermissionError):
            current=collect_managers()
        self.assertTrue(reconcile(previous,current)['objects'][0]['stale'])

    def test_download_classification_does_not_return_url_or_secrets(self):
        self.assertEqual(download_kind('https://user:secret@github.com/org/repo/releases/download/v1/tool.zip?token=secret'),'GitHub Releases')
        self.assertEqual(download_kind('https://github.com/org/repo'),'其他网站')
        self.assertEqual(download_kind('https://registry.npmjs.org/tool/-/tool.tgz'),'包仓库')
        self.assertEqual(download_kind('file:///C:/Downloads/package.whl'),'本地 / 离线文件')

    def test_winget_registry_marker_not_catalog_match(self):
        obj={'kind':'software','wingetPackageId':'Publisher.Tool'};enrich(obj)
        self.assertEqual(obj['softwareOrigin']['channel'],'winget')
        self.assertEqual(obj['softwareOrigin']['download'],'未知')
        obj={'kind':'software','wingetSource':'winget'};enrich(obj)
        self.assertEqual(obj['softwareOrigin']['channel'],'未知')

    def test_npm_custom_prefix_and_no_credentials_in_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);prefix=home/'global'
            self.write(home/'.npmrc',f'prefix={prefix}\n//registry.example/:_authToken=secret-value\n')
            self.write(prefix/'node_modules/tool/package.json',{'name':'tool','version':'1','bin':'index.js','packageManager':'yarn@4'})
            with patch('manager_inventory.Path.home',return_value=home):
                self.assertIn(prefix,npm_prefixes())
                data=collect_packages(locations=[('npm',prefix/'node_modules')])
            self.assertEqual(data['objects'][0]['managedChannel'],'npm')
            self.assertNotIn('secret-value',json.dumps(data))

    def test_manual_override_survives_automatic_channel(self):
        obj={'kind':'software','managedChannel':'Scoop','managerReceipt':'receipt'}
        enrich(obj,{'channel':'手动安装'})
        self.assertEqual(obj['softwareOrigin']['channel'],'手动安装')
        self.assertEqual(obj['detectedOrigin']['channel'],'Scoop')
