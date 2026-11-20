"""Live-mode setup check shown in the app (no packages are imported or installed)."""

import sys

import pytest

from inspectbot.ui.live_check import LIVE_PACKAGES, live_problems

ok_spec = lambda name: object()  # noqa: E731
no_spec = lambda name: None  # noqa: E731
supported = (3, 11) <= sys.version_info[:2] <= (3, 13)


@pytest.mark.skipif(not supported, reason="needs a CrewAI-supported Python")
def test_ready_with_packages_and_key_in_environment(tmp_path):
    assert live_problems(tmp_path, find_spec=ok_spec, environ={"ANTHROPIC_API_KEY": "sk-test"}) == []


@pytest.mark.skipif(not supported, reason="needs a CrewAI-supported Python")
def test_key_read_from_env_file(tmp_path):
    (tmp_path / ".env").write_text("OTHER=1\nANTHROPIC_API_KEY='sk-test'\n")
    assert live_problems(tmp_path, find_spec=ok_spec, environ={}) == []


def test_missing_packages_named_with_install_command(tmp_path):
    problems = live_problems(tmp_path, find_spec=no_spec, environ={"ANTHROPIC_API_KEY": "sk-test"})
    text = " ".join(problems)
    assert "crewai" in text and 'pip install -e ".[dev,agents,ui]"' in text
    assert all(p in text for p in LIVE_PACKAGES)


def test_empty_key_counts_as_missing(tmp_path):
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=\n")
    problems = live_problems(tmp_path, find_spec=ok_spec, environ={})
    assert any("ANTHROPIC_API_KEY" in p for p in problems)
