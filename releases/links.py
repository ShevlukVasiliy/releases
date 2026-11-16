"""Parse explicit Yandex Music album URLs or one numeric ID per line."""
import re
from urllib.parse import urlsplit

URL = re.compile(r'https?://[^\s<>\]\[()]+', re.I)
VALID_HOSTS = {'music.yandex.ru', 'music.yandex.com', 'music.yandex.by', 'music.yandex.kz', 'music.yandex.com.tr'}

def parse_album_ids(text):
    ids = []
    for line in text.splitlines():
        stripped = line.strip()
        if re.fullmatch(r'[0-9]+', stripped): ids.append(int(stripped))
        for match in URL.finditer(line):
            try:
                url = urlsplit(match.group().rstrip('.,;'))
                found = re.match(r'^/album/([0-9]+)(?:/|$)', url.path)
                if url.hostname and url.hostname.lower() in VALID_HOSTS and found: ids.append(int(found.group(1)))
            except ValueError: continue
    return list(dict.fromkeys(n for n in ids if 0 < n <= 2**63-1))
