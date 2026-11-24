from datetime import timedelta

import pytest

import click
from click.testing import CliRunner


def run(args, **kwargs):
    @click.command()
    @click.option("--wait", type=click.Duration(**kwargs))
    def cli(wait):
        click.echo(repr(wait))

    return CliRunner().invoke(cli, args)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("90s", timedelta(seconds=90)),
        ("15m", timedelta(minutes=15)),
        ("1h30m", timedelta(hours=1, minutes=30)),
        ("2d", timedelta(days=2)),
        ("1d2h3m4s", timedelta(days=1, hours=2, minutes=3, seconds=4)),
        ("45", timedelta(seconds=45)),
        ("2H", timedelta(hours=2)),
    ],
)
def test_valid_durations(text, expected):
    result = run(["--wait", text])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == repr(expected)


@pytest.mark.parametrize("text", ["", "abc", "1x", "30m1h", "1h1h", "1.5h", "-5m", "1h 30m"])
def test_invalid_durations_are_rejected(text):
    result = run(["--wait", text])
    assert result.exit_code == 2
    assert "is not a valid duration" in result.output


def test_timedelta_and_int_values_pass_through():
    duration = click.Duration()
    assert duration.convert(timedelta(minutes=5), None, None) == timedelta(minutes=5)
    assert duration.convert(30, None, None) == timedelta(seconds=30)


def test_minimum_and_maximum():
    bounds = {"min": timedelta(minutes=1), "max": timedelta(hours=1)}
    assert run(["--wait", "30s"], **bounds).exit_code == 2
    assert "shorter than the minimum" in run(["--wait", "30s"], **bounds).output
    assert "longer than the maximum" in run(["--wait", "2h"], **bounds).output
    assert run(["--wait", "1h"], **bounds).exit_code == 0


def test_metavar_and_name():
    @click.command()
    @click.option("--wait", type=click.Duration())
    def cli(wait):
        pass

    help_text = CliRunner().invoke(cli, ["--help"]).output
    assert "--wait DURATION" in help_text
    assert click.Duration().name == "duration"
