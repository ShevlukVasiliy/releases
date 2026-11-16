import argparse
import os
import sys
import webbrowser
from pathlib import Path
from .db import Database
from .server import Server
from filelock import FileLock, Timeout


def main():
    default_data = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'Releases' if sys.platform == 'win32' else Path('~/Library/Application Support/Releases').expanduser()
    default_library = Path.home() / ('Music' if sys.platform == 'win32' else 'Music/Music/Media.localized/Music')
    parser = argparse.ArgumentParser(description="Local Releases service")
    parser.add_argument("--port", type=int, default=8771)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("RELEASES_DATA_DIR", str(default_data))).expanduser())
    parser.add_argument("--library", type=Path, default=default_library)
    parser.add_argument("--downloads", type=Path, default=Path(os.environ.get("NEW_RELEASES_DUMP_DIR", "~/Music/YandexDump")).expanduser())
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = FileLock(str(args.data_dir / "service.lock"))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        parser.exit(1, "Releases уже запущен с этим каталогом данных.\n")
    db = Database(args.data_dir / "releases.sqlite3")
    db.initialize()
    try:
        server = Server(("127.0.0.1", args.port), db, args.library, args.downloads)
    except OSError as exc:
        parser.exit(1, f"Cannot start local server: {exc}\n")
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Releases: {url}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        lock.release()

if __name__ == "__main__":
    main()
