"""Stateless LayerMap API and bundled frontend. No submitted YAML is persisted."""
from pathlib import Path
from typing import Literal
from threading import BoundedSemaphore

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from generate_diagram import render
from network_model import ModelError, load_model, MAX_YAML_BYTES
from view_model import ViewScope, prepare_view, limits, MAX_HTTP_BYTES, MAX_RENDER_JOBS, MAX_SVG_BYTES

ROOT = Path(__file__).parent
render_slots = BoundedSemaphore(MAX_RENDER_JOBS)
app = FastAPI(title='LayerMap', docs_url=None, redoc_url=None, openapi_url=None)


class BodyLimit:
    def __init__(self, app):
        self.application = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.application(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            size += len(chunk)
            if size > MAX_HTTP_BYTES:
                response = JSONResponse({'errors':[{'message':f'リクエストは{MAX_HTTP_BYTES // 1048576} MiB以下にしてください','path':'','line':None,'column':None}]}, status_code=413)
                return await response(scope, receive, send)
            chunks.append(chunk)
            if not message.get('more_body'):
                break
        replayed = False
        async def replay():
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {'type':'http.request', 'body':b''.join(chunks), 'more_body':False}
        await self.application(scope, replay, send)


# Pure ASGI middleware caps bodies before JSON/YAML parsing, including chunked requests.
app.add_middleware(BodyLimit)


@app.middleware('http')
async def headers(request, call_next):
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    return response


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    yaml_text: str = Field(max_length=MAX_YAML_BYTES)
    view: Literal['all','l1','l2','l3'] = 'all'
    show_bindings: bool = True
    scope: ViewScope = Field(default_factory=ViewScope)


@app.exception_handler(RequestValidationError)
async def request_error(request, exc):
    return JSONResponse({'errors':[{'message':'描画リクエストの形式が不正です','path':'.'.join(map(str,e['loc'])), 'line':None,'column':None} for e in exc.errors()]},status_code=422)


@app.get('/api/limits')
def get_limits():
    return limits()


@app.get('/api/health')
def health():
    return {'status':'ok'}


@app.get('/api/sample')
def sample():
    return {'yaml_text': (ROOT/'lan-sample.yaml').read_text(encoding='utf-8')}


# Only these bundled files can be read through the sample API.
SAMPLES = {
    'base': {'id':'base', 'title':'基本構成', 'description':'業務PCと来客PC。4機器・3ケーブル・2 VLAN。', 'filename':'lan-sample.yaml', 'file':ROOT/'lan-sample.yaml'},
    'add-pc': {'id':'add-pc', 'title':'機器追加版', 'description':'業務VLAN 10にHQ-PC-03を追加。5機器・4ケーブル・2 VLAN。', 'filename':'01-add-pc-vlan10.yaml', 'file':ROOT/'samples'/'01-add-pc-vlan10.yaml'},
    'add-vlan': {'id':'add-vlan', 'title':'VLAN追加版', 'description':'HQ-PC-03を新設VLAN 30へ移動。5機器・4ケーブル・3 VLAN。', 'filename':'02-add-vlan30.yaml', 'file':ROOT/'samples'/'02-add-vlan30.yaml'},
}


@app.get('/api/samples')
def list_samples():
    return {'samples':[{k:v for k,v in sample.items() if k!='file'} for sample in SAMPLES.values()]}


@app.get('/api/samples/{sample_id}')
def get_sample(sample_id: str):
    sample = SAMPLES.get(sample_id)
    if sample is None:
        raise HTTPException(status_code=404, detail='サンプルが見つかりません')
    return {'id':sample_id,'filename':sample['filename'],'yaml_text':sample['file'].read_text(encoding='utf-8')}


@app.post('/api/render')
def draw(request: RenderRequest):
    if not render_slots.acquire(blocking=False):
        return JSONResponse({'errors':[{'message':'描画処理が混み合っています。少し待って再試行してください。','path':'','line':None,'column':None}]},status_code=429,headers={'Retry-After':'1'})
    try:
        # Validate the COMPLETE input before applying any display filters.
        model,ix = load_model(request.yaml_text,with_index=True)
        layers = None if request.view == 'all' else [request.view]
        projected,display,catalog = prepare_view(model,ix,request.scope,layers,request.show_bindings)
        svg = render(projected,layers=layers,show_bindings=request.show_bindings,context_notes=display['context_notes']) if display['status']=='ready' else ''
        if len(svg.encode('utf-8'))>MAX_SVG_BYTES:
            svg='';display['status']='too_large';display['message']='SVGの容量上限を超えています。表示範囲をさらに絞り込んでください。'
        return {'svg':svg,'devices':[{'id':d['id'],'name':d.get('name') or d['id'],'site':str(d.get('location',{}).get('site','')),'groups':d.get('groups',[])} for d in ix['devices'].values()],
                'visible_devices':[d['id'] for d in projected['devices']],
                'counts':{'devices':len(model['devices']),'links':len(model['l1']['links']),'vlans':len(model['l2']['vlans'])},
                'display':display,'catalog':catalog,'limits':limits()}
    except ModelError as exc:
        return JSONResponse({'errors':[{'message':str(exc),'path':exc.path,'line':exc.line,'column':exc.column}]}, status_code=422)
    finally:
        render_slots.release()



# Serving is local and bundled; no CDN, storage service, or external fonts are used.
DIST = ROOT/'frontend'/'dist'
if DIST.exists():
    app.mount('/assets', StaticFiles(directory=DIST/'assets'), name='assets')


@app.get('/')
def index():
    if not (DIST/'index.html').exists():
        return JSONResponse({'error':'Frontend build is missing. Build the Docker image.'}, status_code=503)
    return FileResponse(DIST/'index.html')
