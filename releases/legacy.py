"""Import existing settings without modifying the original files."""
import json
from pathlib import Path
from .library import normalize

def import_legacy(db, exclude_path, cache_path):
    excluded = set()
    if Path(exclude_path).exists():
        excluded = {normalize(line.split('#', 1)[0].strip()) for line in Path(exclude_path).read_text(encoding='utf-8').splitlines()} - {''}
    cached = {}
    if Path(cache_path).exists():
        cached = json.loads(Path(cache_path).read_text(encoding='utf-8'))
        if not isinstance(cached, dict): raise ValueError('Некорректный формат прежнего кэша')
    excluded_count = matched_count = invalid_count = 0
    with db.connect() as conn:
        artists = {row['normalized_name']: row['id'] for row in conn.execute('SELECT id,normalized_name FROM artists WHERE track_count>0')}
        if not artists: raise ValueError('Сначала просканируйте медиатеку')
        for key in excluded:
            if key in artists:
                excluded_count += conn.execute('UPDATE artists SET excluded=1 WHERE id=? AND excluded=0', (artists[key],)).rowcount
        for key, value in cached.items():
            if key not in artists or value is None: continue
            if not isinstance(value, dict) or not str(value.get('id', '')).isdigit() or not isinstance(value.get('name'), str) or not value['name']:
                invalid_count += 1
                continue
            matched_count += conn.execute("INSERT OR IGNORE INTO artist_matches(artist_id,provider_id,provider_name,checked_at,is_manual) VALUES(?,?,?,CURRENT_TIMESTAMP,0)", (artists[key], str(value['id']), value['name'])).rowcount
    return {'excluded_added': excluded_count, 'matches_added': matched_count, 'invalid': invalid_count, 'excluded_not_in_library': len(excluded-set(artists))}
