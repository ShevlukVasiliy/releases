"""Yandex Music lookup and comparison with the indexed library."""
import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from yandex_music import Client
from yandex_music.exceptions import YandexMusicError
from yandex_music.utils.request import Request
from .library import normalize, SPLIT
from .credentials import get_token

BRACKETS = re.compile(r'\s*[\(\[][^\)\]]*[\)\]]')
REMIX = re.compile(r'remix|mix\b|dub\b|edit\b|version|acoustic|instrumental|sped up|slowed|live', re.I)

def keys(title, version=None):
    base = title.split(':')[0]
    variants = {title, BRACKETS.sub('', title), base, BRACKETS.sub('', base)}
    if version:
        variants.add(f'{title} ({version})')
    return {key for text in variants if (key := normalize(text))}

def local_catalog(db):
    artists = defaultdict(lambda: {'albums': set(), 'tracks': set()})
    with db.connect() as conn:
        rows = conn.execute('SELECT metadata_json FROM files').fetchall()
    for row in rows:
        data = json.loads(row[0]); artist = data.get('artist')
        if not artist: continue
        names = {artist} | {n.strip() for credit in [artist, *data.get('credited', [])] for n in SPLIT.split(credit) if n.strip()}
        for name in names:
            entry = artists[normalize(name)]
            if data.get('album'): entry['albums'].update(keys(data['album']))
            if data.get('title'): entry['tracks'].update(keys(data['title']))
    return artists

def token():
    value = get_token()
    if value: return value
    value = os.environ.get('YANDEX_MUSIC_TOKEN')
    if value: return value.strip()
    try: return Path('~/.config/new_releases/token').expanduser().read_text(encoding='utf-8').strip() or None
    except FileNotFoundError: return None

def retry(fn, *args, **kwargs):
    for attempt in range(3):
        try: return fn(*args, **kwargs)
        except (YandexMusicError, OSError):
            if attempt == 2: raise
            time.sleep(2 ** attempt)

class YandexCatalog:
    def __init__(self):
        self.client = Client(token(), request=Request(timeout=15)).init()

    def find(self, name):
        result = retry(self.client.search, name, type_='artist', nocorrect=True)
        for artist in (result.artists.results[:5] if result and result.artists else []):
            if normalize(artist.name) == normalize(name):
                return {'id': str(artist.id), 'name': artist.name}
        return None

    def albums(self, artist_id):
        out = []; page = 0
        while True:
            response = retry(self.client.artists_direct_albums, artist_id, page=page, page_size=100)
            for album in response.albums:
                out.append({'id': album.id, 'title': album.title, 'version': album.version,
                    'type': album.type, 'year': album.year, 'date': (album.release_date or '')[:10] or str(album.year or '?'),
                    'tracks': album.track_count, 'artists': [str(a.id) for a in (album.artists or [])]})
            if not response.pager or (page + 1) * response.pager.per_page >= response.pager.total: break
            page += 1
        return out

def compare(albums, artist_id, artist_name, local, opts):
    missing = []
    for a in albums:
        if a['artists'] and str(artist_id) not in a['artists']: continue
        if a.get('version') and a['version'].casefold().startswith('feat') and normalize(artist_name) in normalize(a['version']): continue
        if opts.get('no_singles') and a['type'] == 'single': continue
        if opts.get('no_remixes') and REMIX.search(f"{a['title']} {a.get('version') or ''}"): continue
        if opts.get('since') and (a.get('year') or 0) < opts['since']: continue
        variants = keys(a['title'], a.get('version'))
        if variants & local['albums'] or (a['type'] == 'single' and variants & local['tracks']): continue
        missing.append({'id': a['id'], 'title': a['title'] + (f" ({a['version']})" if a.get('version') else ''),
            'type': a['type'], 'date': a['date'], 'tracks': a['tracks'], 'url': f"https://music.yandex.ru/album/{a['id']}"})
    return sorted(missing, key=lambda item: item['date'], reverse=True)

def check(db, provider, artist_ids, opts, progress=lambda *_: None):
    local = local_catalog(db)
    with db.connect() as conn:
        artists = {r['id']: dict(r) for r in conn.execute('SELECT id,name,normalized_name FROM artists WHERE track_count>0')}
    results = []
    for index, artist_id in enumerate(artist_ids, 1):
        artist = artists.get(artist_id)
        if not artist:
            results.append({'id': artist_id, 'error': 'Артист не найден в индексе'})
        else:
            try:
                with db.connect() as conn:
                    match = conn.execute("SELECT provider_id,provider_name FROM artist_matches WHERE artist_id=? AND (is_manual=1 OR (provider_id IS NOT NULL AND checked_at >= datetime('now','-30 days')) OR (provider_id IS NULL AND checked_at >= datetime('now','-1 day')))", (artist_id,)).fetchone()
                info = {'id': match[0], 'name': match[1]} if match and match[0] else (None if match else provider.find(artist['name']))
                if not match:
                    with db.connect() as conn:
                        conn.execute("INSERT INTO artist_matches(artist_id,provider_id,provider_name,checked_at) VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(artist_id) DO UPDATE SET provider_id=excluded.provider_id,provider_name=excluded.provider_name,checked_at=CURRENT_TIMESTAMP", (artist_id, info['id'] if info else None, info['name'] if info else None))
                result = {'id': artist_id, 'name': artist['name'], 'found': bool(info), 'missing': []}
                if info:
                    with db.connect() as conn:
                        cache = conn.execute("SELECT albums_json FROM catalog_cache WHERE provider_id=? AND fetched_at >= datetime('now','-1 day')", (info['id'],)).fetchone()
                    albums = json.loads(cache[0]) if cache else provider.albums(info['id'])
                    if not cache:
                        with db.connect() as conn:
                            conn.execute("INSERT INTO catalog_cache(provider_id,albums_json,fetched_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(provider_id) DO UPDATE SET albums_json=excluded.albums_json,fetched_at=CURRENT_TIMESTAMP", (info['id'], json.dumps(albums, ensure_ascii=False)))
                    result.update(yandex_url=f"https://music.yandex.ru/artist/{info['id']}", missing=compare(albums, info['id'], info['name'], local[artist['normalized_name']], opts))
                results.append(result)
            except Exception as exc:
                results.append({'id': artist_id, 'name': artist['name'], 'error': f'{type(exc).__name__}: {exc}'})
        progress(index, len(artist_ids), results[-1])
    return {'artists': len(artist_ids), 'errors': sum(bool(r.get('error')) for r in results), 'results': results}
