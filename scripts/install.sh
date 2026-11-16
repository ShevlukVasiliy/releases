#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' 'Для установки нужен uv: https://docs.astral.sh/uv/getting-started/installation/' >&2
  exit 1
fi
case "${SHELL:-}" in
  */zsh) shell_config="${ZDOTDIR:-$HOME}/.zshrc" ;;
  */bash) shell_config="$HOME/.bashrc" ;;
  *) printf '%s\n' 'Поддерживаются zsh и bash. Запустите установщик из подходящей оболочки или задайте SHELL.' >&2; exit 1 ;;
esac
cd "$project_dir"
uv sync --locked
# The project directory is passed as data; Python quotes it for the shell.
"$project_dir/.venv/bin/python" - "$project_dir" "$shell_config" <<'PY'
import datetime
import os
import shlex
import shutil
import sys
from pathlib import Path
project, config = Path(sys.argv[1]), Path(sys.argv[2]).expanduser()
start, end = '# >>> releases installer >>>', '# <<< releases installer <<<'
config.parent.mkdir(parents=True, exist_ok=True)
text = config.read_text(encoding='utf-8') if config.exists() else ''
if start in text or end in text:
    if text.count(start) != 1 or text.count(end) != 1 or text.index(start) > text.index(end):
        raise SystemExit('Не удалось безопасно обновить существующий блок releases в настройках оболочки.')
    before, after = text.split(start, 1)
    _, after = after.split(end, 1)
    text = before.rstrip('\n') + '\n' + after.lstrip('\n')
if config.exists():
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = config.with_name(config.name + '.releases-backup-' + stamp)
    shutil.copy2(config, backup)
    print(f'Резервная копия: {backup}')
command = shlex.quote(str(project / '.venv/bin/releases'))
block = f"{start}\nalias releases={shlex.quote(command)}\n{end}\n"
# Keep the user's original mode and replace atomically in the same directory.
tmp = config.with_name(config.name + f'.releases-{os.getpid()}.tmp')
try:
    tmp.write_text(text.rstrip('\n') + '\n\n' + block, encoding='utf-8')
    if config.exists(): os.chmod(tmp, config.stat().st_mode & 0o777)
    os.replace(tmp, config)
finally:
    tmp.unlink(missing_ok=True)
print(f'Команда releases добавлена в {config}. Откройте новую оболочку или выполните: source {shlex.quote(str(config))}')
PY
