"""Download into the user's chosen folder without overwriting existing files."""
import io
import os
import re
import tempfile
from pathlib import Path
from PIL import Image
from mutagen.id3 import (APIC, ID3, ID3NoHeaderError, TALB, TCMP, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TPUB, TRCK)
from .catalog import retry

GENRES = {
    "pop": "Pop", "rock": "Rock", "rap": "Hip-Hop", "rusrap": "Русский рэп", "rusrock": "Русский рок",
    "ruspop": "Русская поп-музыка", "electronics": "Electronic", "dance": "Dance", "metal": "Metal",
    "alternative": "Alternative", "indie": "Indie", "jazz": "Jazz", "blues": "Blues", "classical": "Classical",
    "soundtrack": "Soundtrack", "films": "Soundtrack", "videogame": "Soundtrack", "folk": "Folk",
    "rnb": "R&B", "soul": "Soul", "reggae": "Reggae", "punk": "Punk", "estrada": "Эстрада",
    "bard": "Авторская песня", "shanson": "Шансон", "children": "Детская", "lounge": "Lounge",
    "ambient": "Ambient", "house": "House", "techno": "Techno", "dnb": "Drum & Bass", "anime": "Anime",
    "kpop": "K-Pop", "jpop": "J-Pop", "local-indie": "Indie", "phonk": "Phonk",
}


def safe_name(s, limit=120):
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", s).strip(" .")
    return s[:limit] or "_"


def album_id_from(s):
    m = re.search(r"album/(\d+)", str(s))
    return int(m.group(1)) if m else int(s)


def parse_album_ids(text):
    """Ссылки music.yandex.ru/album/... или голые id из произвольного текста, без дублей."""
    ids = re.findall(r"album/(\d+)|^\s*(\d+)\s*$", text, re.M)
    return list(dict.fromkeys(int(a or b) for a, b in ids))


def with_version(title, version):
    return f"{title} ({version})" if version else title


def clean_jpeg(data):
    """Любая картинка -> RGB JPEG: Apple Music не переваривает CMYK/PNG-в-APIC и т.п."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def set_cover(tags, jpeg):
    tags.delall("APIC")
    # encoding=0 (ISO-8859-1): Apple не всегда читает UTF-16 в APIC
    tags.add(APIC(encoding=0, mime="image/jpeg", type=3, desc="Cover", data=jpeg))


def tag_file(path, track, album, cover, number, total, disc, discs):
    try:
        ID3(path).delete()  # теги с нуля, без мусора от источника
    except ID3NoHeaderError:
        pass
    tags = ID3()
    tags.add(TIT2(encoding=3, text=with_version(track.title, track.version)))
    tags.add(TPE1(encoding=3, text=", ".join(a.name for a in track.artists) or "Unknown Artist"))
    tags.add(TPE2(encoding=3, text=", ".join(a.name for a in album.artists) or "Unknown Artist"))
    tags.add(TALB(encoding=3, text=with_version(album.title, album.version)))
    tags.add(TRCK(encoding=3, text=f"{number}/{total}"))
    tags.add(TPOS(encoding=3, text=f"{disc}/{discs}"))
    if album.year:
        tags.add(TDRC(encoding=3, text=str(album.year)))
    if album.genre:
        tags.add(TCON(encoding=3, text=GENRES.get(album.genre, album.genre.replace("-", " ").title())))
    if album.labels:
        name = album.labels[0] if isinstance(album.labels[0], str) else album.labels[0].name
        tags.add(TPUB(encoding=3, text=name))
    if album.type == "compilation" or (album.artists and album.artists[0].various):
        tags.add(TCMP(encoding=3, text="1"))
    if cover:
        set_cover(tags, cover)
    tags.save(path, v2_version=3)


def best_mp3(track, allow_preview):
    infos = [i for i in track.get_download_info() if i.codec == "mp3"]
    if not allow_preview:
        infos = [i for i in infos if not i.preview]
    if not infos:
        raise RuntimeError("доступно только превью — нужен токен аккаунта с Плюсом")
    return max(infos, key=lambda i: i.bitrate_in_kbps)


def download_album(client, album_id, root, progress=lambda *_: None):
    album = retry(client.albums_with_tracks, album_id)
    if not album or not album.volumes:
        raise ValueError('Альбом не найден или не содержит треков')
    artist = ', '.join(a.name for a in album.artists) or 'Unknown Artist'
    folder = with_version(album.title, album.version) + (f' ({album.year})' if album.year else '')
    root = Path(root).expanduser().resolve()
    out = root / safe_name(artist) / safe_name(folder)
    if not out.resolve().is_relative_to(root):
        raise ValueError('Папка назначения находится вне каталога загрузки')
    out.mkdir(parents=True, exist_ok=True)
    if not out.resolve().is_relative_to(root):
        raise ValueError('Папка назначения находится вне каталога загрузки')
    cover = None
    if album.cover_uri:
        try: cover = clean_jpeg(retry(album.download_cover_bytes, size='1000x1000'))
        except Exception: pass
    tracks = [(disc, number, track) for disc, volume in enumerate(album.volumes, 1) for number, track in enumerate(volume, 1)]
    downloaded = skipped = unavailable = 0
    for i, (disc, number, track) in enumerate(tracks, 1):
        title = with_version(track.title, track.version)
        prefix = f'{disc}-{number:02d}' if len(album.volumes) > 1 else f'{number:02d}'
        path = out / f'{prefix} {safe_name(title)}.mp3'
        if track.available is False:
            unavailable += 1
        elif path.exists():
            skipped += 1
        else:
            info = retry(best_mp3, track, False)
            fd, temp = tempfile.mkstemp(prefix='.releases-', suffix='.part', dir=out)
            os.close(fd)
            try:
                retry(info.download, temp)
                tag_file(temp, track, album, cover, number, len(album.volumes[disc-1]), disc, len(album.volumes))
                # Hard-link publication fails if another process created the destination.
                try:
                    os.link(temp, path)
                    downloaded += 1
                except FileExistsError:
                    skipped += 1
            finally:
                Path(temp).unlink(missing_ok=True)
        progress(i, len(tracks), title)
    return {'folder': str(out), 'downloaded': downloaded, 'skipped': skipped, 'unavailable': unavailable}
