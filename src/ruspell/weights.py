"""Внешние ресурсы проверки: какие нужны, где лежат и как их скачать.

В пакете весов нет — 58 МБ в колесе не нужны никому, кто пользуется только
словарным слоем. Скачиваются они один раз, командой::

    ruspell-weights download [каталог]             # всё, 58 МБ
    ruspell-weights download-agreement [каталог]   # без частотного словаря, 30 МБ
    python -m ruspell download [каталог]

Каталог по умолчанию — ``$RUSPELL_WEIGHTS_DIR``, иначе ``~/.cache/ruspell``.
Скачивание переживает временные отказы сети: за файлами ходят в публичные
хранилища, а те периодически отдают 503.

Частотный словарь берётся из запиннного коммита, а не из ``master``: ветка —
подвижная ссылка, и ранжирование поехало бы без следа в истории.
"""

from __future__ import annotations

import argparse
import http.client
import os
import shutil
import sys
import time
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

ENV_WEIGHTS_DIR = "RUSPELL_WEIGHTS_DIR"

NAVEC_FILE = "navec_news_v1_1B_250K_300d_100q.tar"
MORPH_FILE = "slovnet_morph_news_v1.tar"
SYNTAX_FILE = "slovnet_syntax_news_v1.tar"
FREQUENCY_FILE = "ru_full.txt"

AGREEMENT_FILES = (NAVEC_FILE, MORPH_FILE, SYNTAX_FILE)
"""Веса, без которых слой согласования не поднимется."""

FREQUENCY_COMMIT = "f8a65e6ddc17e0baa2e366a909986798d8dbe55b"
"""Коммит FrequencyWords, из которого берётся частотный словарь.

Ветка ``master`` — подвижная ссылка: содержимое под ней меняется и исчезает, а
проверка получила бы другое ранжирование без единого следа в истории.
"""

DOWNLOADS: dict[str, str] = {
    # Эмбеддинги и модели разбора проекта Natasha (MIT), ~30 МБ вместе.
    NAVEC_FILE: f"https://storage.yandexcloud.net/natasha-navec/packs/{NAVEC_FILE}",
    MORPH_FILE: f"https://storage.yandexcloud.net/natasha-slovnet/packs/{MORPH_FILE}",
    SYNTAX_FILE: f"https://storage.yandexcloud.net/natasha-slovnet/packs/{SYNTAX_FILE}",
    # Частотный словарь русского языка (hermitdave/FrequencyWords, MIT), 28 МБ.
    # Нужен только для ранжирования вариантов замены: без него работает
    # эвристика по форме слова.
    FREQUENCY_FILE: (
        f"https://raw.githubusercontent.com/hermitdave/FrequencyWords/{FREQUENCY_COMMIT}"
        f"/content/2018/ru/{FREQUENCY_FILE}"
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


def download_files(directory: Path, sources: Mapping[str, str]) -> int:
    """Докачивает недостающее и возвращает суммарный размер файлов в МБ.

    Уже скачанные файлы не трогаются, так что команду можно запускать повторно.
    Битый архив весов ловится там, где он мешает — при загрузке моделей, и
    ``check.build_layers`` откатывается на словарный слой; битый частотный
    словарь — в ``dictionary.frequency_ranker``.

    Args:
        directory: Куда складывать.
        sources: Имена файлов и адреса, откуда их брать.

    Returns:
        Суммарный размер файлов в мегабайтах.
    """
    directory.mkdir(parents=True, exist_ok=True)
    total = 0
    for name, url in sources.items():
        path = directory / name
        if path.exists() and path.stat().st_size > 0:
            print(f"уже на месте: {name}")
        else:
            print(f"скачиваю {name}...")
            download(url, path)
        total += path.stat().st_size
    return total // (1024 * 1024)


def download_weights(directory: Path) -> int:
    """Докачивает всё: веса согласования и частотный словарь (58 МБ).

    Команду можно запускать повторно: целые файлы не перекачиваются.
    """
    return download_files(directory, DOWNLOADS)


def download_agreement_weights(directory: Path) -> int:
    """Докачивает только веса согласования, без частотного словаря (30 МБ).

    Частотный словарь — половина объёма и нужен лишь для ранжирования
    вариантов; без него слой согласования работает полностью, а словарный
    откатывается на эвристику по форме слова.
    """
    return download_files(directory, {name: DOWNLOADS[name] for name in AGREEMENT_FILES})


COMMANDS: dict[str, Callable[[Path], int]] = {
    "download": download_weights,
    "download-agreement": download_agreement_weights,
}
"""Команды консольного скрипта."""


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа команды скачивания весов."""
    parser = argparse.ArgumentParser(
        prog="ruspell-weights",
        description="Скачивание весов slovnet и частотного словаря для ruspell",
    )
    parser.add_argument(
        "command",
        choices=tuple(COMMANDS),
        help="download — всё; download-agreement — без частотного словаря",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        default=None,
        help=f"каталог весов (по умолчанию ${ENV_WEIGHTS_DIR} или ~/.cache/ruspell)",
    )
    arguments = parser.parse_args(argv)
    directory = arguments.directory or default_weights_dir()
    size = COMMANDS[arguments.command](directory)
    print(f"веса ruspell в {directory}: {size} МБ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
