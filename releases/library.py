"""Read-only, incremental indexing of local audio files."""
import json
import os
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from mutagen import File as audio_file

AUDIO_EXT = {'.mp3', '.m4a', '.flac', '.ogg', '.opus', '.wav', '.aac'}
SPLIT = re.compile(r',\s*|\s+&\s+|\s+(?:feat\.?|ft\.?|x)\s+', re.I)
SUFFIX = re.compile(r'\s*[-–—]\s*(single|ep)\s*$', re.I)

def normalize(value):
    value = unicodedata.normalize('NFKC', value or '').casefold().replace('ё', 'е')
    return re.sub(r'[\W_]+', '', SUFFIX.sub('', value))

def read_metadata(path, root):
    parts = path.relative_to(root).parts
    artist = parts[0] if len(parts) >= 2 else None
    album = parts[1] if len(parts) >= 3 else None
    title = path.stem
    credited = []
    error = None
    try:
        audio = audio_file(path, easy=True)
        tags = audio.tags if audio else None
        if tags:
            def first(*names):
                return next((str(tags[name][0]).strip() for name in names if tags.get(name)), None)
            artist = first('albumartist', 'artist') or artist
            album = first('album') or album
            title = first('title') or title
            credited = [str(x) for x in (tags.get('artist') or [])]
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    return {'artist': artist, 'album': album, 'title': title, 'credited': credited, 'read_error': error}

def scan(db, root, progress=lambda *_: None):
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('Папка медиатеки не найдена')
    with db.connect() as conn:
        previous_root = conn.execute("SELECT value FROM settings WHERE key='library_root'").fetchone()
        old = {row['path']: row for row in conn.execute('SELECT * FROM files')} if previous_root and previous_root[0] == str(root) else {}
    # A failed traversal must not delete the previously indexed data.
    paths = []
    def fail(exc):
        raise exc
    for directory, _, filenames in os.walk(root, onerror=fail, followlinks=False):
        for name in filenames:
            path = Path(directory) / name
            if path.suffix.lower() in AUDIO_EXT and not path.is_symlink():
                paths.append(path)
    paths.sort()
    records, aggregate = [], defaultdict(lambda: {'name': None, 'count': 0})
    changed = errors = 0
    for i, path in enumerate(paths, 1):
        stat = path.stat()
        key = str(path)
        before = old.get(key)
        if before and before['size'] == stat.st_size and before['mtime_ns'] == stat.st_mtime_ns and not json.loads(before['metadata_json']).get('read_error'):
            meta = json.loads(before['metadata_json'])
        else:
            meta = read_metadata(path, root)
            changed += 1
        errors += bool(meta.get('read_error'))
        records.append((key, stat.st_size, stat.st_mtime_ns, json.dumps(meta, ensure_ascii=False)))
        artist = meta.get('artist')
        if artist and normalize(artist):
            main = aggregate[normalize(artist)]
            main['name'] = main['name'] or artist
            main['count'] += 1
            names = {n.strip() for c in [artist, *meta.get('credited', [])] for n in SPLIT.split(c) if n.strip()}
            for name in names:
                normalized = normalize(name)
                if normalized:
                    aggregate[normalized]['name'] = aggregate[normalized]['name'] or name
        if i % 100 == 0 or i == len(paths):
            progress(i, len(paths))
    with db.connect() as conn:
        conn.execute('DELETE FROM files')
        conn.executemany('INSERT INTO files(path,size,mtime_ns,metadata_json,indexed_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP)', records)
        conn.execute('UPDATE artists SET track_count=0')
        conn.executemany('''INSERT INTO artists(normalized_name,name,track_count) VALUES(?,?,?)
            ON CONFLICT(normalized_name) DO UPDATE SET name=excluded.name,track_count=excluded.track_count''',
            [(k, v['name'], v['count']) for k, v in aggregate.items()])
        conn.execute("INSERT INTO settings(key,value) VALUES('library_root',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(root),))
    return {'files': len(paths), 'read': changed, 'reused': len(paths)-changed, 'errors': errors,
            'artists': sum(1 for a in aggregate.values() if a['count'] > 0)}
