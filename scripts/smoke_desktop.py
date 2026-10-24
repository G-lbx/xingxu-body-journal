"""Exercise a built Mac app in an isolated directory without Python on its PATH."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def api(url, path, method='GET', body=None):
    request = urllib.request.Request(url+path, method=method,
        data=None if body is None else json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with opener.open(request, timeout=100) as response:
        return json.load(response)

def smoke(executable, fixture):
    env = dict(os.environ, PATH='/usr/bin:/bin:/usr/sbin:/sbin')
    for key in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'):
        env.pop(key, None)
    with tempfile.TemporaryDirectory(prefix='xingxu-smoke-') as temporary:
        directory = Path(temporary) / 'data'
        def start():
            child = subprocess.Popen([str(executable), '--headless', '--no-browser', '--port', '0', '--data-dir', str(directory)], env=env)
            try:
                for _ in range(200):
                    if child.poll() is not None:
                        raise RuntimeError(f'App exited during startup: {child.returncode}')
                    try:
                        metadata = json.loads((directory/'desktop-service.json').read_text())
                        url = f"http://127.0.0.1:{metadata['port']}"
                        if api(url, '/api/health').get('desktop_instance') == metadata['token']:
                            return child, url
                    except (OSError, ValueError):
                        pass
                    time.sleep(.2)
                raise RuntimeError('App startup timed out')
            except BaseException:
                child.terminate(); child.wait(timeout=15)
                raise
        child = None
        try:
            child, url = start()
            state = api(url, '/api/state')
            assert state['records'] == [] and state['profile']['age'] is None
            assert state['ocr_available'] and state['ocr_engine'] == 'Apple Vision', state
            for asset in ('/', '/assets/app.js', '/assets/armor-theme.css', '/assets/chart.js'):
                with opener.open(url+asset) as response:
                    assert response.status == 200 and len(response.read()) > 100
            result = api(url, '/api/upload', 'POST', {'name': 'synthetic.png', 'dataUrl': 'data:image/png;base64,'+base64.b64encode(fixture.read_bytes()).decode()})
            assert result['engine'] == 'Apple Vision', result
            for field, expected in {'weight': 75.25, 'body_fat': 20.1, 'bmi': 24.6, 'muscle_mass': 55.2, 'measured_at': '2024-01-20T08:00'}.items():
                assert result['fields'][field] == expected, (field, result)
            saved = api(url, '/api/records', 'POST', {**result['fields'], 'upload_id': result['upload_id'], 'source': 'ocr', 'note': 'Fictional CI fixture'})
            assert saved['record']['weight'] == 75.25
            child.terminate(); child.wait(timeout=15); child = None
            child, url = start()
            state = api(url, '/api/state')
            assert len(state['records']) == 1 and state['records'][0]['weight'] == 75.25
            assert state['analysis'], state
            print('PASS: native bundled OCR, empty first run, assets, save, restart persistence, analysis; no Python on child PATH.', flush=True)
        finally:
            if child is not None and child.poll() is None:
                child.terminate(); child.wait(timeout=15)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('executable', type=Path)
    parser.add_argument('fixture', type=Path)
    args = parser.parse_args()
    smoke(args.executable.resolve(), args.fixture.resolve())
