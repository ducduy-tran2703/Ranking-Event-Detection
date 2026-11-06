import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from infra.serve_qdrant_dashboard import create_app


def test_browser_compression_headers_still_return_valid_collections_json(tmp_path, monkeypatch):
    fixture = json.loads(Path('tests/fixtures/rag/qdrant_collections_brotli.json').read_text('utf-8'))
    (tmp_path / 'index.html').write_text('<html>Qdrant</html>', encoding='utf-8')

    def upstream(request):
        if 'br' in request.headers.get('accept-encoding', ''):
            return httpx.Response(200, content=bytes.fromhex(fixture['brotli_hex']),
                                  headers={'content-encoding': 'br', 'content-type': 'application/json'})
        return httpx.Response(200, json=fixture['plain'])

    client_class = httpx.AsyncClient

    def client(*args, **kwargs):
        return client_class(*args, transport=httpx.MockTransport(upstream), **kwargs)

    monkeypatch.setattr(httpx, 'AsyncClient', client)
    with TestClient(create_app(tmp_path)) as browser:
        response = browser.get('/collections', headers={'Accept-Encoding': 'gzip, deflate, br, zstd'})
        assert response.status_code == 200
        assert response.json()['result'] == fixture['plain']['result']
