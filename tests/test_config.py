from __future__ import annotations

from pathlib import Path

import pytest
from ytscript.config import Config, ConfigError, find_config_file, load_config


def write_config(tmp_path: Path, body: str, name: str = "ytscript.toml") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_flat_toml(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
        channel = "@somechannel"
        language = "de"
        initial_backfill = 12
        output_formats = ["txt", "md"]
        """,
    )
    config = load_config(path=path, env={})
    assert config.channel == "@somechannel"
    assert config.language == "de"
    assert config.initial_backfill == 12
    assert config.output_formats == ("txt", "md")


def test_loads_namespaced_toml(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[ytscript]\nchannel = "@x"\nlanguage = "fr"\n')
    assert load_config(path=path, env={}).language == "fr"


def test_env_overrides_file_and_overrides_win(tmp_path: Path) -> None:
    path = write_config(tmp_path, 'channel = "@fromfile"\nlanguage = "en"\n')
    env = {"YTSCRIPT_LANGUAGE": "es", "YTSCRIPT_INITIAL_BACKFILL": "7", "YTSCRIPT_KEEP_AUDIO": "yes"}
    config = load_config(path=path, env=env)
    assert (config.language, config.initial_backfill, config.keep_audio) == ("es", 7, True)

    config = load_config(path=path, env=env, overrides={"language": "ja", "channel": None})
    assert config.language == "ja"
    assert config.channel == "@fromfile"


def test_auto_language_becomes_none() -> None:
    assert Config(channel="@x", language="auto").language is None


def test_missing_config_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(path=tmp_path / "nope.toml", env={})


def test_validate_rejects_bad_values() -> None:
    with pytest.raises(ConfigError, match="no channel"):
        Config().validate()
    with pytest.raises(ConfigError, match="unknown backend"):
        Config(channel="@x", backend="wav2vec").validate()
    with pytest.raises(ConfigError, match="unknown output format"):
        Config(channel="@x", output_formats=("pdf",)).validate()
    with pytest.raises(ConfigError, match="initial_backfill"):
        Config(channel="@x", initial_backfill=0).validate()


def test_find_config_file_walks_up(tmp_path: Path) -> None:
    (tmp_path / "ytscript.toml").write_text('channel = "@x"\n', encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_config_file(nested) == tmp_path / "ytscript.toml"
