"""Тесты каталога весов и скачивания.

В сеть тесты не ходят: скачивание подменяется, проверяется политика повторов и
работа с каталогом.
"""

from __future__ import annotations

import hashlib

import pytest

from ruspell import weights

SOURCES = {"file.tar": "https://example.invalid/file.tar"}


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class TestDefaultWeightsDir:
    def test_environment_variable_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv(weights.ENV_WEIGHTS_DIR, str(tmp_path))
        assert weights.default_weights_dir() == tmp_path

    def test_without_variable_it_is_the_user_cache(self, monkeypatch):
        monkeypatch.delenv(weights.ENV_WEIGHTS_DIR, raising=False)
        assert weights.default_weights_dir().name == "ruspell"


class TestMissingWeights:
    def test_empty_directory_misses_everything(self, tmp_path):
        assert weights.missing_weights(tmp_path) == list(weights.AGREEMENT_FILES)

    def test_present_files_are_not_missing(self, tmp_path):
        for name in weights.AGREEMENT_FILES:
            (tmp_path / name).write_bytes(b"tar")
        assert weights.missing_weights(tmp_path) == []

    def test_frequency_dictionary_is_not_required(self, tmp_path):
        for name in weights.AGREEMENT_FILES:
            (tmp_path / name).write_bytes(b"tar")
        assert not (tmp_path / weights.FREQUENCY_FILE).exists()
        assert weights.missing_weights(tmp_path) == []


class TestDownload:
    def test_retries_until_it_succeeds(self, monkeypatch, tmp_path):
        attempts = []

        def flaky(url: str, path):
            attempts.append(url)
            if len(attempts) < 3:
                raise TimeoutError("сеть отвалилась")
            path.write_bytes(b"tar")

        monkeypatch.setattr(weights, "fetch", flaky)
        monkeypatch.setattr(weights.time, "sleep", lambda _: None)
        weights.download("https://example.invalid/file.tar", tmp_path / "file.tar")
        assert len(attempts) == 3

    def test_gives_up_after_all_attempts(self, monkeypatch, tmp_path):
        def always_fails(url: str, path):
            raise ConnectionError("503")

        monkeypatch.setattr(weights, "fetch", always_fails)
        monkeypatch.setattr(weights.time, "sleep", lambda _: None)
        with pytest.raises(RuntimeError, match="Не удалось скачать"):
            weights.download("https://example.invalid/file.tar", tmp_path / "file.tar")


class TestDownloadFiles:
    def test_intact_file_is_not_downloaded_again(self, monkeypatch, tmp_path):
        downloaded = []
        monkeypatch.setattr(weights, "CHECKSUMS", {"file.tar": digest(b"tar")})
        monkeypatch.setattr(weights, "download", lambda url, path: downloaded.append(url))
        (tmp_path / "file.tar").write_bytes(b"tar")
        assert weights.download_files(tmp_path, SOURCES) == 0
        assert downloaded == []

    def test_missing_file_is_downloaded(self, monkeypatch, tmp_path):
        monkeypatch.setattr(weights, "CHECKSUMS", {"file.tar": digest(b"tar" * 1024)})
        monkeypatch.setattr(weights, "download", lambda url, path: path.write_bytes(b"tar" * 1024))
        weights.download_files(tmp_path / "new", SOURCES)
        assert (tmp_path / "new" / "file.tar").exists()

    def test_corrupted_file_is_downloaded_again(self, monkeypatch, tmp_path):
        # Обрезанная выгрузка непуста, и по размеру её от готового файла не
        # отличить: без сверки она осталась бы на диске навсегда.
        downloaded = []
        monkeypatch.setattr(weights, "CHECKSUMS", {"file.tar": digest(b"tar")})

        def restore(url, path):
            downloaded.append(url)
            path.write_bytes(b"tar")

        monkeypatch.setattr(weights, "download", restore)
        (tmp_path / "file.tar").write_bytes("обрезано".encode())
        weights.download_files(tmp_path, SOURCES)
        assert downloaded == list(SOURCES.values())
        assert (tmp_path / "file.tar").read_bytes() == b"tar"

    def test_wrong_checksum_after_download_is_an_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(weights, "CHECKSUMS", {"file.tar": digest(b"tar")})
        wrong = "чужое".encode()
        monkeypatch.setattr(weights, "download", lambda url, path: path.write_bytes(wrong))
        with pytest.raises(RuntimeError, match="Контрольная сумма"):
            weights.download_files(tmp_path, SOURCES)


class TestDownloadCommands:
    def test_full_download_takes_the_frequency_dictionary_too(self, monkeypatch, tmp_path):
        asked = []
        monkeypatch.setattr(
            weights,
            "download_files",
            lambda directory, sources: asked.append(
                tuple(sources),
            ),
        )
        weights.download_weights(tmp_path)
        assert weights.FREQUENCY_FILE in asked[0]

    def test_agreement_download_skips_the_frequency_dictionary(self, monkeypatch, tmp_path):
        asked = []
        monkeypatch.setattr(
            weights,
            "download_files",
            lambda directory, sources: asked.append(
                tuple(sources),
            ),
        )
        weights.download_agreement_weights(tmp_path)
        assert asked == [weights.AGREEMENT_FILES]


class TestMain:
    def test_download_command_uses_the_given_directory(self, monkeypatch, tmp_path):
        used = []
        monkeypatch.setitem(weights.COMMANDS, "download", lambda directory: used.append(directory))
        assert weights.main(["download", str(tmp_path)]) == 0
        assert used == [tmp_path]

    def test_agreement_command_is_available(self, monkeypatch, tmp_path):
        called = []
        monkeypatch.setitem(
            weights.COMMANDS,
            "download-agreement",
            lambda directory: called.append(directory),
        )
        assert weights.main(["download-agreement", str(tmp_path)]) == 0
        assert called == [tmp_path]

    def test_unknown_command_is_rejected(self):
        with pytest.raises(SystemExit):
            weights.main(["upload"])
