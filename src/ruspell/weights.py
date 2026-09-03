"""Внешние ресурсы проверки: какие нужны, где лежат и как их скачать.

В пакете весов нет — 58 МБ в колесе не нужны никому, кто пользуется только
словарным слоем. Скачиваются они один раз, командой::

    ruspell-weights download [каталог]
    python -m ruspell download [каталог]

Каталог по умолчанию — ``$RUSPELL_WEIGHTS_DIR``, иначе ``~/.cache/ruspell``.
Скачивание переживает временные отказы сети: за файлами ходят в публичные
хранилища, а те периодически отдают 503.
"""

from __future__ import annotations

import argparse
import http.client
import os
import shutil
import sys
import time
import urllib.request
from collections.abc import Sequence
from pathlib import Path

ENV_WEIGHTS_DIR = "RUSPELL_WEIGHTS_DIR"

NAVEC_FILE = "navec_news_v1_1B_250K_300d_100q.tar"
MORPH_FILE = "slovnet_morph_news_v1.tar"
SYNTAX_FILE = "slovnet_syntax_news_v1.tar"
FREQUENCY_FILE = "ru_full.txt"

AGREEMENT_FILES = (NAVEC_FILE, MORPH_FILE, SYNTAX_FILE)
"""Веса, без которых слой согласования не поднимется."""

DOWNLOADS: dict[str, str] = {
    # Эмбеддинги и модели разбора проекта Natasha (MIT), ~30 МБ вместе.
    NAVEC_FILE: f"https://storage.yandexcloud.net/natasha-navec/packs/{NAVEC_FILE}",
    MORPH_FILE: f"https://storage.yandexcloud.net/natasha-slovnet/packs/{MORPH_FILE}",
    SYNTAX_FILE: f"https://storage.yandexcloud.net/natasha-slovnet/packs/{SYNTAX_FILE}",
    # Частотный словарь русского языка (hermitdave/FrequencyWords, MIT), 28 МБ.
    # Нужен только для ранжирования вариантов замены: без него работает
    # эвристика по форме слова.
    FREQUENCY_FILE: (
        "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/ru/"
        f"{FREQUENCY_FILE}"
    ),
}

ATTEMPTS = 6
"""Сколько раз пытаться скачать файл, удваивая паузу между попытками."""

TIMEOUT = 300
"""Секунд на соединение и чтение: файлы большие, каналы бывают узкими."""


def default_weights_dir() -> Path:
    """Возвращает каталог весов по умолчанию.

    Переменная окружения ``RUSPELL_WEIGHTS_DIR`` перекрывает всё; без неё —
    ``~/.cache/ruspell``.
    """
    override = os.environ.get(ENV_WEIGHTS_DIR)
    return Path(override) if override else Path.home() / ".cache" / "ruspell"


def missing_weights(directory: Path) -> list[str]:
    """Возвращает имена весов согласования, которых нет в каталоге."""
    return [name for name in AGREEMENT_FILES if not (directory / name).exists()]


def fetch(url: str, path: Path) -> None:
    """Скачивает файл во временный ``.part`` и переименовывает по завершении.

    Оборванная закачка не должна выглядеть готовым файлом: следующий запуск
    иначе примет обрезанный tar за скачанный и упадёт уже при загрузке весов.
    """
    part = path.with_name(path.name + ".part")
    with urllib.request.urlopen(url, timeout=TIMEOUT) as response, part.open("wb") as target:
        shutil.copyfileobj(response, target)
    part.replace(path)


def download(url: str, path: Path) -> None:
    """Скачивает файл, переживая временные отказы сети.

    Args:
        url: Адрес файла.
        path: Куда положить.

    Raises:
        RuntimeError: Если исчерпаны все попытки.
    """
    for attempt in range(ATTEMPTS):
        try:
            fetch(url, path)
        except (OSError, http.client.HTTPException) as exc:
            # urllib.error.URLError и TimeoutError — подклассы OSError, так что
            # тут ловятся все сетевые отказы разом, а не только таймаут.
            if attempt == ATTEMPTS - 1:
                raise RuntimeError(f"Не удалось скачать {url}: {exc}") from exc
            time.sleep(2**attempt)
            continue
        return


def download_weights(directory: Path) -> int:
    """Докачивает недостающие ресурсы и возвращает их суммарный размер в МБ.

    Уже скачанные файлы не трогаются, так что команду можно запускать повторно.
    """
    directory.mkdir(parents=True, exist_ok=True)
    total = 0
    for name, url in DOWNLOADS.items():
        path = directory / name
        if path.exists() and path.stat().st_size > 0:
            print(f"уже на месте: {name}")
        else:
            print(f"скачиваю {name}...")
            download(url, path)
        total += path.stat().st_size
    return total // (1024 * 1024)


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа команды скачивания весов."""
    parser = argparse.ArgumentParser(
        prog="ruspell-weights",
        description="Скачивание весов slovnet и частотного словаря для ruspell",
    )
    parser.add_argument("command", choices=("download",), help="что сделать")
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        default=None,
        help=f"каталог весов (по умолчанию ${ENV_WEIGHTS_DIR} или ~/.cache/ruspell)",
    )
    arguments = parser.parse_args(argv)
    directory = arguments.directory or default_weights_dir()
    size = download_weights(directory)
    print(f"веса ruspell в {directory}: {size} МБ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
