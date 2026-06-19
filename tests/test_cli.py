import pytest

from forza.cli.parser import build_parser


def test_root_help_is_cp1252_safe():
    help_text = build_parser().format_help()
    help_text.encode("cp1252")


def test_root_help_advertises_db_doctor():
    help_text = build_parser().format_help()

    assert "python -m forza maintenance db-doctor" in help_text
    assert "python -m forza maintenance db-doctor --json" in help_text


def test_root_help_advertises_db_reset():
    help_text = build_parser().format_help()

    assert "python -m forza maintenance db-reset --yes" in help_text


def test_root_help_uses_diagnostics_label():
    help_text = build_parser().format_help()

    assert "DIAGNOSTICS" in help_text
    assert "GUI Diagnostics section" in help_text
    assert "DEVELOPER TOOLS" not in help_text
    assert "Developer Tools screen" not in help_text


def test_shared_config_before_subcommand_is_preserved():
    args = build_parser().parse_args([
        "--config", "custom.ini",
        "--debug",
        "maintenance",
        "db-doctor",
    ])
    assert args.config == "custom.ini"
    assert args.debug is True


def test_shared_config_after_subcommand_is_preserved():
    args = build_parser().parse_args([
        "maintenance",
        "db-doctor",
        "--config", "custom.ini",
        "--debug",
    ])
    assert args.config == "custom.ini"
    assert args.debug is True


def test_root_config_defaults_without_subcommand():
    args = build_parser().parse_args([])
    assert args.config == "forza_config.ini"
    assert args.debug is False


def test_root_help_does_not_advertise_removed_lab_cli():
    help_text = build_parser().format_help()

    removed_lab_command = "python -m forza " + "lab"
    assert removed_lab_command not in help_text
    assert "LAB / DEVELOPER TOOLS" not in help_text


@pytest.mark.parametrize(
    "argv",
    [
        ["lab"],
        ["lab", "ground-truth"],
        ["lab", "prompt-bench"],
        ["lab", "diagnose"],
        ["lab", "config-" + "bench"],
    ],
)
def test_removed_lab_cli_is_not_registered(argv):
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)


def test_db_reset_requires_confirmation_flag():
    args = build_parser().parse_args([
        "maintenance",
        "db-reset",
        "--yes",
    ])
    assert args.yes is True


def test_removed_old_reset_cli_alias_is_not_registered():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["maintenance", "runtime-" + "reset", "--yes"])
    assert ("runtime-" + "reset") not in build_parser().format_help()


def test_db_upgrade_subcommand_registered():
    args = build_parser().parse_args(["maintenance", "db-upgrade"])
    from forza.cli.maintenance import cmd_db_upgrade
    assert args.func is cmd_db_upgrade


@pytest.mark.parametrize("command", ["db-" + "check", "db-" + "current"])
def test_removed_redundant_database_aliases_are_not_registered(command):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["maintenance", command])


def test_removed_review_identity_fix_cli_is_not_registered():
    command = "review-identity-" + "fix"

    with pytest.raises(SystemExit):
        build_parser().parse_args(["maintenance", command])

    assert command not in build_parser().format_help()


def test_config_check_subcommand_registered():
    args = build_parser().parse_args(["config-check"])
    from forza.cli.maintenance import cmd_config_check
    assert args.func is cmd_config_check



def test_root_help_advertises_version_option():
    assert "--version" in build_parser().format_help()
