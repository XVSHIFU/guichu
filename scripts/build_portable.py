"""Build a clean Windows x64 portable folder from an explicit source allowlist."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = '3.13.12'

def main():
    if sys.platform != 'win32':
        raise SystemExit('Build on Windows x64.')
    parser=argparse.ArgumentParser();parser.add_argument('--name',default='guichu-windows-x64');args=parser.parse_args()
    if not args.name.replace('-','').isalnum():raise SystemExit('Use an alphanumeric output name')
    output = ROOT / 'release' / args.name
    if output.exists():
        raise SystemExit('Output already exists; move it aside before rebuilding: ' + str(output))
    subprocess.run(['npm.cmd', '--prefix', str(ROOT/'app'), 'run', 'build'], check=True)
    app = output / 'app'
    runtime = app / 'runtime'
    runtime.mkdir(parents=True)
    cache = ROOT / 'release' / f'python-{VERSION}-embed-amd64.zip'
    url = f'https://www.python.org/ftp/python/{VERSION}/python-{VERSION}-embed-amd64.zip'
    if not cache.exists():
        urllib.request.urlretrieve(url, cache)
    with zipfile.ZipFile(cache) as archive:
        archive.extractall(runtime)
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--ignore-installed', '--only-binary=:all:', '--platform', 'win_amd64', '--python-version', '3.13', '--target', str(runtime/'Lib/site-packages'), '-r', str(ROOT/'app/requirements-portable.lock')], check=True)
    (runtime/'python313._pth').write_text('python313.zip\n.\n..\nLib/site-packages\nLib/site-packages/win32\nLib/site-packages/win32/lib\nLib/site-packages/Pythonwin\nimport site\n', encoding='utf-8')
    # pywin32's post-install script is not run for vendored dependencies.
    for dll in (runtime/'Lib/site-packages/pywin32_system32').glob('*.dll'):
        shutil.copy2(dll, runtime/dll.name)
    for pattern in ('*.py','*.ps1'):
        for source in (ROOT/'app').glob(pattern):
            shutil.copy2(source, app/source.name)
    for name in ('dist','agent'):
        shutil.copytree(ROOT/'app'/name, app/name, ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for source in ROOT.glob('*.cmd'):
        shutil.copy2(source, output/source.name)
    shutil.copytree(ROOT/'docs',output/'docs')
    shutil.copy2(ROOT/'app/README.md',app/'README.md')
    for name in ('README.md','CHANGELOG.md'):
        shutil.copy2(ROOT/name, output/name)
    subprocess.run([str(runtime/'python.exe'), '-c', 'import server, mcp, psutil, yaml, win32crypt; print("Portable imports OK")'], cwd=app, check=True)
    manifest = {'python': VERSION, 'python_source': url, 'python_archive_sha256': hashlib.sha256(cache.read_bytes()).hexdigest(), 'files': {str(p.relative_to(output)).replace('\\','/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in output.rglob('*') if p.is_file() and '__pycache__' not in p.parts}}
    (output/'build-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    archive_path = ROOT/'release'/(args.name+'.zip')
    with zipfile.ZipFile(archive_path,'w',zipfile.ZIP_DEFLATED) as archive:
        for p in output.rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:
                archive.write(p,Path(output.name)/p.relative_to(output))
    print(archive_path)

if __name__ == '__main__':
    main()
