"""Local HTTP service backed by Flask and Waitress."""
import json
import secrets
import sys
from pathlib import Path
from flask import Flask, jsonify, request, Response
from waitress import create_server
from .jobs import JobRunner
from .links import parse_album_ids
from .credentials import set_token


def create_app(db, library, downloads, csrf_token, port, start_jobs=True):
    app = Flask(__name__, static_folder='static', static_url_path='')
    app.config.update(MAX_CONTENT_LENGTH=200_000, PORT=port)
    if start_jobs:
        app.extensions['jobs'] = JobRunner(db)

    @app.before_request
    def protect():
        host = f"127.0.0.1:{app.config['PORT']}"
        if request.host != host:
            return jsonify(error='Invalid host'), 403
        if request.method != 'GET':
            if request.headers.get('Origin') != f'http://{host}' or not secrets.compare_digest(request.headers.get('X-Releases-Token', ''), csrf_token):
                return jsonify(error='Forbidden'), 403

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
        return response

    @app.errorhandler(413)
    def too_large(_): return jsonify(error='Слишком большой запрос'), 413

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict): raise ValueError('Некорректный запрос')
        return data

    def valid_id(value): return type(value) is int and 0 < value <= 2**63-1

    def enqueue(kind, params):
        result = app.extensions['jobs'].enqueue(kind, params)
        return (jsonify(id=result), 202) if result else (jsonify(error='Такая задача уже выполняется'), 409)

    @app.get('/')
    def index():
        page = (Path(app.static_folder) / 'index.html').read_text(encoding='utf-8').replace('__TOKEN__', csrf_token)
        return Response(page, content_type='text/html; charset=utf-8')

    @app.get('/api/status')
    def status(): return jsonify(service='releases', **db.status())

    @app.get('/api/jobs')
    def list_jobs(): return jsonify(db.jobs())

    @app.get('/api/artists')
    def artists():
        with db.connect() as conn:
            rows = conn.execute('SELECT id,name,track_count,excluded FROM artists WHERE track_count>0 ORDER BY name COLLATE NOCASE').fetchall()
            return jsonify([dict(row) for row in rows])

    @app.post('/api/scan')
    def scan(): return enqueue('scan', {'path': str(library)})

    @app.post('/api/legacy')
    def legacy(): return enqueue('legacy', {})

    @app.post('/api/token')
    def save_token():
        try: set_token(body().get('token'))
        except (ValueError, RuntimeError) as exc: return jsonify(error=str(exc)), 400
        return jsonify(ok=True)

    @app.post('/api/exclude')
    def exclude():
        try:
            data = body(); artist_id, excluded = data.get('artist_id'), data.get('excluded')
            if not valid_id(artist_id) or type(excluded) is not bool: raise ValueError('Некорректные данные')
            with db.connect() as conn:
                if not conn.execute('UPDATE artists SET excluded=? WHERE id=? AND track_count>0', (int(excluded), artist_id)).rowcount: raise ValueError('Артист не найден')
            return jsonify(ok=True)
        except ValueError as exc: return jsonify(error=str(exc)), 400

    @app.post('/api/order-preview')
    def order_preview():
        if sys.platform!='darwin': return jsonify(error='Сверка Music доступна только на macOS'),400
        return enqueue('order_preview',{})

    @app.post('/api/order-apply')
    def order_apply():
        try:
            if sys.platform!='darwin': raise ValueError('Сверка Music доступна только на macOS')
            preview_id=body().get('preview_id')
            if not valid_id(preview_id): raise ValueError('Некорректный номер проверки')
            with db.connect() as conn: row=conn.execute("SELECT result_json FROM jobs WHERE id=? AND kind='order_preview' AND status='done'", (preview_id,)).fetchone()
            if not row: raise ValueError('Предварительный просмотр не найден')
            changes=json.loads(row[0]).get('changes')
            if not changes: raise ValueError('Нет изменений для применения')
            return enqueue('order_apply', {'changes':changes})
        except ValueError as exc: return jsonify(error=str(exc)),400

    @app.post('/api/fix-preview')
    def fix_preview():
        if downloads is None: return jsonify(error='Каталог загрузки не настроен'), 400
        return enqueue('fix_preview', {'root':str(downloads)})

    @app.post('/api/fix-apply')
    def fix_apply():
        try:
            preview_id=body().get('preview_id')
            if not valid_id(preview_id): raise ValueError('Некорректный номер проверки')
            with db.connect() as conn: row=conn.execute("SELECT result_json FROM jobs WHERE id=? AND kind='fix_preview' AND status='done'", (preview_id,)).fetchone()
            if not row: raise ValueError('Предварительный просмотр не найден')
            result=json.loads(row[0])
            if not result.get('changes'): raise ValueError('Нет изменений для применения')
            return enqueue('fix_apply', {'preview':result})
        except ValueError as exc: return jsonify(error=str(exc)),400

    @app.post('/api/check')
    def check():
        try:
            data=body(); ids=data.get('artist_ids'); opts=data.get('options', {})
            if not isinstance(ids,list) or not ids or len(ids)>5000 or any(not valid_id(i) for i in ids): raise ValueError('Некорректный список артистов')
            if not isinstance(opts,dict): raise ValueError('Некорректные фильтры')
            since=opts.get('since')
            if since is not None and (type(since) is not int or not 1900<=since<=2100): raise ValueError('Некорректный год')
            with db.connect() as conn: excluded={r['id'] for r in conn.execute('SELECT id FROM artists WHERE excluded=1')}
            ids=[i for i in ids if i not in excluded]
            if not ids: raise ValueError('Все выбранные артисты исключены')
            return enqueue('check', {'artist_ids':list(dict.fromkeys(ids)), 'options':{'since':since,'no_singles':opts.get('no_singles') is True,'no_remixes':opts.get('no_remixes') is True}})
        except ValueError as exc: return jsonify(error=str(exc)), 400

    @app.post('/api/downloads')
    def downloads_list():
        try:
            text=body().get('text')
            if not isinstance(text,str): raise ValueError('Ожидается список ссылок')
            ids=parse_album_ids(text)
            if not ids: raise ValueError('Ссылки на альбомы не найдены')
            if len(ids)>1000: raise ValueError('Не более 1000 альбомов за раз')
            if downloads is None: raise ValueError('Каталог загрузки не настроен')
            created=[app.extensions['jobs'].enqueue('download',{'album_id':i,'root':str(downloads)}) for i in ids]
            return jsonify(found=len(ids),queued=sum(j is not None for j in created)), 202
        except ValueError as exc: return jsonify(error=str(exc)),400

    @app.post('/api/download')
    def download():
        try:
            album_id=body().get('album_id')
            if not valid_id(album_id): raise ValueError('Некорректный номер альбома')
            if downloads is None: raise ValueError('Каталог загрузки не настроен')
            return enqueue('download',{'album_id':album_id,'root':str(downloads)})
        except ValueError as exc: return jsonify(error=str(exc)),400

    @app.post('/api/match')
    def match():
        try:
            data=body(); artist_id,provider_id=data.get('artist_id'),data.get('provider_id')
            if not valid_id(artist_id) or not valid_id(provider_id): raise ValueError('Некорректный номер артиста')
            return enqueue('match',{'artist_id':artist_id,'provider_id':provider_id})
        except ValueError as exc: return jsonify(error=str(exc)),400

    @app.post('/api/import')
    def music_import():
        try:
            if sys.platform!='darwin': raise ValueError('Импорт через приложение Music доступен только на macOS')
            download_id=body().get('download_id')
            if not valid_id(download_id): raise ValueError('Некорректный номер загрузки')
            with db.connect() as conn: row=conn.execute("SELECT result_json FROM jobs WHERE id=? AND kind='download' AND status='done'",(download_id,)).fetchone()
            if not row: raise ValueError('Завершённая загрузка не найдена')
            folder=json.loads(row[0]).get('folder')
            if not folder: raise ValueError('Папка загрузки не найдена')
            return enqueue('import',{'folder':folder,'download_id':download_id})
        except ValueError as exc: return jsonify(error=str(exc)),400
    return app

class Server:
    def __init__(self, address, db, library, downloads=None):
        self.app=create_app(db,library,downloads,secrets.token_urlsafe(32),address[1],start_jobs=False)
        self.server=create_server(self.app,host=address[0],port=address[1],threads=4)
        self.server_port=int(self.server.effective_port)
        self.app.config['PORT']=self.server_port
        self.app.extensions['jobs'] = JobRunner(db)
    def serve_forever(self, **kwargs): self.server.run()
    def server_close(self): self.server.close()
