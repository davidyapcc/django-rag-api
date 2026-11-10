import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.qa.management.commands import run_eval as cmd
from evals.runner import run_eval

pytestmark = pytest.mark.django_db


def test_eval_meets_thresholds():
    summary = run_eval().as_dict()
    for metric, floor in cmd.THRESHOLDS.items():
        assert summary[metric] >= floor, (metric, summary)


def test_eval_leaves_no_data():
    from django.contrib.auth import get_user_model

    run_eval()
    assert not get_user_model().objects.filter(username="__eval__").exists()


def test_command_passes(capsys):
    call_command("run_eval", "--verbose-cases")
    assert "eval passed" in capsys.readouterr().out


def test_command_fails_on_regression(monkeypatch):
    monkeypatch.setitem(cmd.THRESHOLDS, "retrieval_hit_rate", 1.01)
    with pytest.raises(CommandError):
        call_command("run_eval")
