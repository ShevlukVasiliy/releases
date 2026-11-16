"""Store tokens in the operating system's credential manager."""
SERVICE = 'local.releases.yandex-music'
ACCOUNT = 'yandex-music'

def backend():
    import sys
    try:
        if sys.platform == 'darwin':
            from keyring.backends.macOS import Keyring
        elif sys.platform == 'win32':
            from keyring.backends.Windows import WinVaultKeyring as Keyring
        else:
            raise RuntimeError('Системное хранилище ключей поддерживается на macOS и Windows')
        selected = Keyring()
        if selected.priority <= 0:
            raise RuntimeError('Системное хранилище ключей недоступно')
        return selected
    except ImportError as exc:
        raise RuntimeError('Не установлен модуль системного хранилища ключей') from exc

def get_token():
    try:
        return backend().get_password(SERVICE, ACCOUNT)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError('Не удалось прочитать токен из системного хранилища ключей') from exc

def set_token(value):
    if not isinstance(value, str) or not value or len(value) > 4096 or any(c.isspace() for c in value):
        raise ValueError('Введите токен без пробелов')
    try:
        backend().set_password(SERVICE, ACCOUNT, value)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError('Не удалось сохранить токен в системном хранилище ключей') from exc
