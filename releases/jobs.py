"""Persisted single-worker jobs, with conservative interruption handling."""
import json
import queue
import threading
from .library import scan
from .catalog import YandexCatalog, check, retry, token
from .download import download_album
from .music import import_album
from .legacy import import_legacy
from .maintenance import preview as preview_fixes, apply as apply_fixes
from .order import preview_order, apply_order
from pathlib import Path

class JobRunner:
    def __init__(self, db):
        self.db = db
        self.lock = threading.Lock()
        self.queue = queue.Queue()
        with db.connect() as conn:
            conn.execute("UPDATE jobs SET status='interrupted', error='Работа прервана перезапуском сервиса', updated_at=CURRENT_TIMESTAMP WHERE status IN ('running','queued')")
        threading.Thread(target=self.worker, daemon=True).start()

    def enqueue(self, kind, params):
        with self.lock, self.db.connect() as conn:
            active = conn.execute("SELECT params_json FROM jobs WHERE kind=? AND status IN ('queued','running')", (kind,)).fetchall()
            if active and (kind != 'download' or any(json.loads(row[0]).get('album_id') == params.get('album_id') for row in active)):
                return None
            cursor = conn.execute("INSERT INTO jobs(kind,status,params_json) VALUES(?,'queued',?)", (kind, json.dumps(params, ensure_ascii=False)))
            job_id = cursor.lastrowid
        self.queue.put((job_id, kind, params))
        return job_id

    def enqueue_scan(self, path):
        return self.enqueue('scan', {'path': str(path)})

    def update(self, job_id, **values):
        values['updated_at'] = None
        keys = list(values)
        sql = ', '.join(f'{k}=CURRENT_TIMESTAMP' if k == 'updated_at' else f'{k}=?' for k in keys)
        params = [values[k] for k in keys if k != 'updated_at'] + [job_id]
        with self.db.connect() as conn:
            conn.execute(f'UPDATE jobs SET {sql} WHERE id=?', params)

    def worker(self):
        while True:
            job_id, kind, params = self.queue.get()
            try:
                self.update(job_id, status='running')
                if kind == 'scan':
                    def progress(done, total):
                        self.update(job_id, progress_json=json.dumps({'done': done, 'total': total}))
                    result = scan(self.db, params['path'], progress)
                elif kind == 'legacy':
                    result = import_legacy(self.db, Path('~/scripts/new_releases_exclude.txt').expanduser(), Path('~/.cache/new_releases/artists.json').expanduser())
                elif kind in ('order_preview', 'order_apply'):
                    def progress(done,total): self.update(job_id,progress_json=json.dumps({'done':done,'total':total}))
                    result = preview_order(YandexCatalog().client,progress) if kind=='order_preview' else apply_order(params['changes'],progress)
                elif kind in ('fix_preview', 'fix_apply'):
                    def progress(done,total): self.update(job_id,progress_json=json.dumps({'done':done,'total':total}))
                    result = preview_fixes(params['root'],progress) if kind=='fix_preview' else apply_fixes(params['preview'],progress)
                elif kind == 'check':
                    partial = []
                    def progress(done, total, item):
                        partial.append(item)
                        self.update(job_id, progress_json=json.dumps({'done': done, 'total': total}), result_json=json.dumps({'results': partial}, ensure_ascii=False))
                    result = check(self.db, YandexCatalog(), params['artist_ids'], params['options'], progress)
                elif kind == 'download':
                    if not token(): raise ValueError('Для загрузки нужен токен Яндекс Музыки')
                    provider = YandexCatalog()
                    def progress(done, total, title):
                        self.update(job_id, progress_json=json.dumps({'done': done, 'total': total, 'current': title}, ensure_ascii=False))
                    result = download_album(provider.client, params['album_id'], params['root'], progress)
                elif kind == 'import':
                    imported = []
                    def progress(done, total, item):
                        imported.append(item)
                        self.update(job_id, progress_json=json.dumps({'done': done, 'total': total, 'current': item['file']}, ensure_ascii=False), result_json=json.dumps({'files': imported}, ensure_ascii=False))
                    result = import_album(self.db, params['folder'], progress)
                elif kind == 'match':
                    provider = YandexCatalog()
                    matches = retry(provider.client.artists, params['provider_id'])
                    if not matches: raise ValueError('Артист не найден в Яндекс Музыке')
                    match = matches[0]
                    with self.db.connect() as conn:
                        if not conn.execute('SELECT 1 FROM artists WHERE id=? AND track_count>0', (params['artist_id'],)).fetchone():
                            raise ValueError('Артист не найден в медиатеке')
                        conn.execute("INSERT INTO artist_matches(artist_id,provider_id,provider_name,checked_at,is_manual) VALUES(?,?,?,CURRENT_TIMESTAMP,1) ON CONFLICT(artist_id) DO UPDATE SET provider_id=excluded.provider_id,provider_name=excluded.provider_name,checked_at=CURRENT_TIMESTAMP,is_manual=1", (params['artist_id'], str(match.id), match.name))
                    result = {'artist_id': params['artist_id'], 'provider_id': str(match.id), 'name': match.name}
                else:
                    raise ValueError('Неизвестный тип задачи')
                self.update(job_id, status='done', result_json=json.dumps(result, ensure_ascii=False))
            except Exception as exc:
                self.update(job_id, status='error', error=f'{type(exc).__name__}: {exc}')
            finally:
                self.queue.task_done()
