"""Import downloaded files through Music's AppleScript interface."""
import subprocess
from pathlib import Path

# Arguments are passed separately, never interpolated into AppleScript source.
SCRIPT = r'''
on run argv
    set sourcePath to item 1 of argv
    set oldID to item 2 of argv
    tell application "Music"
        set lib to library playlist 1
        if oldID is not "" then
            try
                set matches to (every file track of lib whose persistent ID is oldID)
                if (count of matches) > 0 then
                    set foundTrack to item 1 of matches
                    return (persistent ID of foundTrack) & linefeed & POSIX path of (location of foundTrack as alias)
                end if
            end try
            error "Ранее импортированный трек не найден или его файл недоступен; автоматический повтор остановлен"
        end if
        set newTrack to add (POSIX file sourcePath) to lib
        set trackID to persistent ID of newTrack
        set trackPath to POSIX path of (location of newTrack as alias)
        return trackID & linefeed & trackPath
    end tell
end run
'''

def add_to_music(path, existing_id=''):
    result = subprocess.run(['osascript', '-e', SCRIPT, '--', str(path), existing_id], capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Music не подтвердил импорт')
    lines = result.stdout.rstrip('\n').split('\n', 1)
    if len(lines) != 2 or not lines[0] or not lines[1]:
        raise RuntimeError('Music не вернул идентификатор и расположение файла; проверьте медиатеку перед повтором')
    location = Path(lines[1])
    if not location.is_file():
        raise RuntimeError('Music вернул недоступный путь; проверьте медиатеку перед повтором')
    return {'persistent_id': lines[0], 'location': str(location)}

def import_album(db, folder, progress=lambda *_: None, add=add_to_music):
    root = Path(folder).resolve()
    if not root.is_dir(): raise ValueError('Папка загруженного альбома не найдена')
    files = sorted(p for p in root.glob('*.mp3') if p.is_file() and not p.is_symlink())
    if not files: raise ValueError('В папке альбома нет MP3')
    results = []
    for index, file in enumerate(files, 1):
        stat = file.stat()
        with db.connect() as conn:
            previous = conn.execute('SELECT persistent_id,size,mtime_ns FROM music_imports WHERE path=?', (str(file),)).fetchone()
        if previous and not previous['persistent_id']:
            item = {'file': file.name, 'status': 'error', 'error': 'Результат предыдущей попытки неизвестен: проверьте медиатеку вручную перед повтором'}
        elif previous and (previous['size'] != stat.st_size or previous['mtime_ns'] != stat.st_mtime_ns):
            item = {'file': file.name, 'status': 'error', 'error': 'Исходный файл изменился после импорта; нужна ручная проверка'}
        else:
            try:
                if not previous:
                    with db.connect() as conn:
                        conn.execute('INSERT INTO music_imports(path,size,mtime_ns,persistent_id,location) VALUES(?,?,?,NULL,NULL)', (str(file), stat.st_size, stat.st_mtime_ns))
                imported = add(file, previous['persistent_id'] if previous else '')
                with db.connect() as conn:
                    conn.execute('INSERT INTO music_imports(path,size,mtime_ns,persistent_id,location) VALUES(?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET persistent_id=excluded.persistent_id,location=excluded.location', (str(file), stat.st_size, stat.st_mtime_ns, imported['persistent_id'], imported['location']))
                item = {'file': file.name, 'status': 'verified' if previous else 'imported', **imported}
            except Exception as exc:
                item = {'file': file.name, 'status': 'error', 'error': str(exc)}
        results.append(item)
        progress(index, len(files), item)
    return {'folder': str(root), 'files': results, 'errors': sum(item['status']=='error' for item in results)}
