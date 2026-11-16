"""Preview and apply MP3 metadata fixes with backups."""
import os
import shutil
import tempfile
from pathlib import Path
from mutagen.id3 import ID3, ID3NoHeaderError, TPE2
from PIL import Image
import io
import re
from .download import clean_jpeg, set_cover

def fix_file(path):
    """Починка тегов существующего mp3. Возвращает список исправлений."""
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        return ["нет ID3-тегов"]
    fixes = []
    for fid in ("TIT2", "TPE1", "TPE2", "TALB", "TCON"):
        frame = tags.get(fid)
        if frame:
            cleaned = [re.sub(r"\s+", " ", str(t)).strip() for t in frame.text]
            if cleaned != [str(t) for t in frame.text]:
                frame.text = cleaned
                fixes.append(f"{fid}: пробелы")
    if not tags.get("TPE2") and tags.get("TPE1"):
        tags.add(TPE2(encoding=3, text=str(tags["TPE1"].text[0])))
        fixes.append("album artist ← artist")
    covers = tags.getall("APIC")
    if covers:
        img = Image.open(io.BytesIO(covers[0].data))
        if img.format != "JPEG" or img.mode != "RGB" or len(covers) > 1 or covers[0].encoding != 0:
            set_cover(tags, clean_jpeg(covers[0].data))
            fixes.append("обложка → RGB JPEG")
    if tags.version != (2, 3, 0):
        fixes.append(f"ID3v2.{tags.version[1]} → v2.3")
    if fixes:
        tags.save(path, v2_version=3)
    return fixes


def preview(root, progress=lambda *_:None):
    root = Path(root).expanduser().resolve()
    if not root.is_dir(): raise ValueError('Папка загрузок не найдена')
    files = sorted(p for p in root.rglob('*.mp3') if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root))
    changes, errors = [], []
    with tempfile.TemporaryDirectory(prefix='releases-preview-') as tmp:
        for i, path in enumerate(files, 1):
            try:
                stat = path.stat(); copy = Path(tmp) / 'track.mp3'
                shutil.copy2(path, copy)
                fixes = fix_file(copy)
                if fixes and fixes != ['нет ID3-тегов']:
                    changes.append({'path':str(path), 'size':stat.st_size, 'mtime_ns':stat.st_mtime_ns, 'fixes':fixes})
            except Exception as exc:
                errors.append({'path':str(path), 'error':str(exc)})
            progress(i,len(files))
    return {'root':str(root), 'files':len(files), 'changes':changes, 'errors':errors}

def apply(preview_result, progress=lambda *_:None):
    root = Path(preview_result['root']).resolve(); changes=preview_result['changes']; results=[]
    for i, entry in enumerate(changes, 1):
        path=Path(entry['path']); temp=None
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(root): raise ValueError('Путь за пределами папки загрузок')
            stat=path.stat()
            if (stat.st_size,stat.st_mtime_ns)!=(entry['size'],entry['mtime_ns']): raise ValueError('Файл изменился после предварительного просмотра')
            backup=path.with_name(path.name+'.releases-backup')
            if backup.exists(): raise ValueError('Резервная копия уже существует; файл пропущен')
            fd,temp=tempfile.mkstemp(prefix='.releases-fix-',suffix='.mp3',dir=path.parent);os.close(fd)
            shutil.copy2(path,temp); fixes=fix_file(temp)
            if fixes != entry['fixes']: raise ValueError('Предлагаемые изменения изменились; выполните новую проверку')
            current=path.stat()
            if (current.st_size,current.st_mtime_ns)!=(entry['size'],entry['mtime_ns']): raise ValueError('Файл изменился во время обработки')
            # Exclusive creation avoids overwriting any previous backup.
            with path.open('rb') as source, backup.open('xb') as target:
                shutil.copyfileobj(source,target)
            shutil.copystat(path,backup)
            os.replace(temp,path); temp=None
            results.append({'path':str(path),'backup':str(backup),'fixes':fixes})
        except Exception as exc:
            results.append({'path':str(path),'error':str(exc)})
        finally:
            if temp: Path(temp).unlink(missing_ok=True)
        progress(i,len(changes))
    return {'results':results,'errors':sum(bool(r.get('error')) for r in results)}
