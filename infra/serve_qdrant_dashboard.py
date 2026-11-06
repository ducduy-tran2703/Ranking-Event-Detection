"""Serve official Qdrant UI assets with a local proxy to the existing native server.

This starts no Qdrant database. The indexer continues using port 6333 unchanged.
"""

import argparse
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

_HOP_HEADERS = {
    'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
    'te', 'trailer', 'transfer-encoding', 'upgrade',
}


def create_app(assets):
    assets = Path(assets)
    if not (assets / 'index.html').is_file():
        raise ValueError('Missing official Qdrant Web UI index.html')

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(base_url='http://127.0.0.1:6333',
                                     timeout=120, trust_env=False) as client:
            app.state.qdrant = client
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.mount('/dashboard', StaticFiles(directory=assets, html=True))

    @app.api_route('/{path:path}', methods=['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
    async def proxy(request: Request, path: str):
        headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in _HOP_HEADERS | {'host', 'content-length', 'accept-encoding'}}
        # Browsers advertise Brotli/zstd even when this httpx installation cannot decode them.
        # Keep the local upstream uncompressed instead of stripping an undecoded encoding header.
        headers['accept-encoding'] = 'identity'
        # Keep destination fixed; paths from the browser cannot choose an upstream host.
        url = httpx.URL('http://127.0.0.1:6333').copy_with(
            path=request.url.path, query=request.url.query.encode('ascii'))
        try:
            result = await request.app.state.qdrant.request(
                request.method, url, headers=headers, content=await request.body())
        except httpx.HTTPError:
            return JSONResponse({'error': 'Native Qdrant on port 6333 is unavailable'}, status_code=502)
        # httpx decodes compressed bodies; Response computes their actual content length.
        response_headers = {k: v for k, v in result.headers.items()
                            if k.lower() not in _HOP_HEADERS | {'content-length', 'content-encoding'}}
        return Response(result.content, status_code=result.status_code, headers=response_headers)

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', default='data/tools/qdrant-web-ui-v0.2.20/dist')
    parser.add_argument('--port', type=int, default=6335)
    args = parser.parse_args()
    uvicorn.run(create_app(args.assets), host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
