"""Review and update track order through the Music application on macOS."""
import json
import re
import subprocess
import tempfile
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from .catalog import retry
from .download import with_version

def order_key(value):
    value = unicodedata.normalize("NFKC", str(value)).casefold().replace("ё", "е")
    return " ".join(re.findall(r"[^\W_]+", value, flags=re.UNICODE))


def match_album_order(client, artist, album_name, titles):
    local = [order_key(title) for title in titles]
    if len(set(local)) != len(local):
        raise ValueError("повторяющиеся названия треков")
    search = retry(client.search, f"{artist} {album_name}", type_="album", nocorrect=True)
    candidates = []
    for a in (search.albums.results if search and search.albums else [])[:15]:
        names = [a.name for a in (a.artists or [])]
        if order_key(with_version(a.title, a.version)) != order_key(album_name):
            continue
        if order_key(artist) not in {order_key(", ".join(names)), *(order_key(n) for n in names)}:
            continue
        candidates.append(a)
    matches = []
    for candidate in candidates:
        full = retry(client.albums_with_tracks, candidate.id)
        if not full or not full.volumes:
            continue
        mapping = defaultdict(list)
        for disc, volume in enumerate(full.volumes, 1):
            for number, track in enumerate(volume, 1):
                mapping[order_key(with_version(track.title, track.version))].append(
                    (number, len(volume), disc, len(full.volumes)))
        if all(len(mapping[t]) == 1 for t in local):
            matches.append(tuple(mapping[t][0] for t in local))
    if not matches:
        raise ValueError("точное совпадение альбома и треков не найдено")
    if len(set(matches)) != 1:
        raise ValueError("найдены издания с разным порядком")
    return matches[0]


MUSIC_READ = r"""
const t = Application("Music").libraryPlaylists[0].fileTracks;
JSON.stringify({ids:t.id(), persistent:t.persistentID(), titles:t.name(), artists:t.artist(),
  albumArtists:t.albumArtist(), albums:t.album(), numbers:t.trackNumber(), totals:t.trackCount(),
  discs:t.discNumber(), discTotals:t.discCount()});
"""
MUSIC_WRITE = r"""
ObjC.import('Foundation');
function run(argv) {
  const raw = $.NSString.stringWithContentsOfFileEncodingError(argv[0], $.NSUTF8StringEncoding, null).js;
  const changes = JSON.parse(raw), tracks = Application('Music').libraryPlaylists[0].fileTracks;
  // Один снимок медиатеки на порцию вместо семи обращений для каждого трека.
  const ids = tracks.id(), persistent = tracks.persistentID(), titles = tracks.name(), albums = tracks.album();
  const numbers = tracks.trackNumber(), totals = tracks.trackCount(), discs = tracks.discNumber(), discTotals = tracks.discCount();
  const lookup = new Map(ids.map((id, i) => [id, i]));
  let updated = 0, errors = [];
  for (const c of changes) {
    try {
      const i = lookup.get(c.id);
      if (i === undefined || persistent[i] !== c.persistent || titles[i] !== c.title || albums[i] !== c.album) throw Error('трек изменился после проверки');
      const current = [numbers[i], totals[i], discs[i], discTotals[i]];
      if (current.some((v, j) => v !== c.old[j])) throw Error('номера изменились после проверки');
      const t = tracks.byId(c.id);
      if (current[0] !== c.values[0]) t.trackNumber = c.values[0];
      if (current[1] !== c.values[1]) t.trackCount = c.values[1];
      if (current[2] !== c.values[2]) t.discNumber = c.values[2];
      if (current[3] !== c.values[3]) t.discCount = c.values[3];
      updated++;
    } catch (e) { errors.push(c.album + ' — ' + c.title + ': ' + String(e)); }
  }
  return JSON.stringify({updated, errors});
}
"""


def music_script(script, *args):
    result = subprocess.run(["osascript", "-l", "JavaScript", "-e", script, "--", *args],
                            capture_output=True, text=True, check=False, timeout=120)
    if result.returncode:
        raise RuntimeError("Apple Music: " + (result.stderr.strip() or "не удалось обратиться к медиатеке"))
    return json.loads(result.stdout)


def preview_order(client, progress=lambda *_:None):
    data=music_script(MUSIC_READ); groups=defaultdict(list); skipped=[]
    for i,title in enumerate(data['titles']):
        artist=data['albumArtists'][i] or data['artists'][i]; album=data['albums'][i]
        if not artist or not album or not title:
            skipped.append('Пропущен трек без артиста или альбома'); continue
        groups[(artist,album)].append({'id':data['ids'][i], 'persistent':data['persistent'][i], 'title':title, 'album':album,
            'old':[data[k][i] for k in ('numbers','totals','discs','discTotals')]})
    changes=[]; issues=[]
    def process(item):
        (artist,album),tracks=item
        values=match_album_order(client,artist,album,[t['title'] for t in tracks])
        return [dict(t,values=list(v)) for t,v in zip(tracks,values) if t['old']!=list(v)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(process,item):item[0] for item in groups.items()}
        for done,future in enumerate(as_completed(futures),1):
            artist,album=futures[future]
            try: changes.extend(future.result())
            except Exception as exc: issues.append(f'{artist} — {album}: {exc}')
            progress(done,len(groups))
    return {'albums':len(groups),'changes':changes,'skipped':len(skipped),'issues':issues}

def apply_order(changes, progress=lambda *_:None):
    updated=0; errors=[]
    for offset in range(0,len(changes),50):
        batch=changes[offset:offset+50]
        try:
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',suffix='.json') as f:
                json.dump(batch,f,ensure_ascii=False);f.flush(); result=music_script(MUSIC_WRITE,f.name)
            updated+=result['updated']; errors.extend(result['errors'])
        except Exception as exc: errors.append(f'Не удалось применить группу из {len(batch)} треков: {exc}')
        progress(offset+len(batch),len(changes))
    return {'updated':updated,'errors':errors}
