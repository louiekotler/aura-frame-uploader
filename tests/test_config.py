import pytest

from aura_upload.config import Config, load_config
from aura_upload.errors import ConfigError, FrameNotAllowed

FRAME_A = "aaaaaaaa-0000-0000-0000-000000000000"
FRAME_B = "bbbbbbbb-0000-0000-0000-000000000000"


def write(tmp_path, text):
    p = tmp_path / "config.toml"
    p.write_text(text)
    return p


def test_missing_config_refuses_every_write(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    with pytest.raises(FrameNotAllowed):
        cfg.resolve_frame(FRAME_A)


def test_empty_allowlist_refuses(tmp_path):
    cfg = load_config(write(tmp_path, "allowed_frame_ids = []\n"))
    with pytest.raises(FrameNotAllowed):
        cfg.resolve_frame(FRAME_A)


def test_unlisted_frame_refused(tmp_path):
    cfg = load_config(write(tmp_path, f'allowed_frame_ids = ["{FRAME_A}"]\n'))
    with pytest.raises(FrameNotAllowed) as e:
        cfg.resolve_frame(FRAME_B)
    assert FRAME_B in str(e.value)


def test_allowed_frame_passes(tmp_path):
    cfg = load_config(write(tmp_path, f'allowed_frame_ids = ["{FRAME_A}"]\n'))
    assert cfg.resolve_frame(FRAME_A) == FRAME_A


def test_single_allowed_frame_is_implicit_default(tmp_path):
    cfg = load_config(write(tmp_path, f'allowed_frame_ids = ["{FRAME_A}"]\n'))
    assert cfg.resolve_frame(None) == FRAME_A


def test_multiple_allowed_frames_require_explicit_choice(tmp_path):
    cfg = load_config(
        write(tmp_path, f'allowed_frame_ids = ["{FRAME_A}", "{FRAME_B}"]\n')
    )
    with pytest.raises(FrameNotAllowed):
        cfg.resolve_frame(None)
    assert cfg.resolve_frame(FRAME_B) == FRAME_B


def test_default_frame_must_be_allowlisted(tmp_path):
    p = write(
        tmp_path,
        f'allowed_frame_ids = ["{FRAME_A}"]\n\n[defaults]\nframe_id = "{FRAME_B}"\n',
    )
    with pytest.raises(ConfigError):
        load_config(p)


def test_default_frame_used_when_no_flag(tmp_path):
    cfg = load_config(
        write(
            tmp_path,
            f'allowed_frame_ids = ["{FRAME_A}", "{FRAME_B}"]\n'
            f'\n[defaults]\nframe_id = "{FRAME_B}"\n',
        )
    )
    assert cfg.resolve_frame(None) == FRAME_B


def test_allowlist_must_be_strings(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "allowed_frame_ids = [1, 2]\n"))


def test_invalid_toml_reports_the_file(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "allowed_frame_ids = [\n"))


def test_is_allowed():
    cfg = Config(allowed_frame_ids=[FRAME_A])
    assert cfg.is_allowed(FRAME_A)
    assert not cfg.is_allowed(FRAME_B)
