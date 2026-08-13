import pytest

from aura_upload.cli import build_parser


def parse(argv):
    return build_parser().parse_args(argv)


@pytest.mark.parametrize(
    "argv",
    [
        ["--json", "list"],
        ["list", "--json"],
    ],
)
def test_json_flag_accepted_on_either_side_of_the_subcommand(argv):
    assert getattr(parse(argv), "json", False) is True


def test_json_defaults_off():
    assert getattr(parse(["list"]), "json", False) is False


def test_upload_path_defaults_to_cwd():
    assert parse(["upload"]).path == "."


def test_upload_takes_an_explicit_path():
    assert parse(["upload", "~/photos"]).path == "~/photos"


def test_remove_requires_one_identifier():
    with pytest.raises(SystemExit):
        parse(["remove"])
    with pytest.raises(SystemExit):
        parse(["remove", "--local-id", "a", "--asset-id", "b"])
    assert parse(["remove", "--local-id", "a"]).local_id == "a"


def test_upload_defaults_are_conservative():
    """Skips duplicates and stops on first failure unless told otherwise."""
    args = parse(["upload"])
    assert args.force is False
    assert args.keep_going is False
    assert args.dry_run is False
    assert args.recursive is False
