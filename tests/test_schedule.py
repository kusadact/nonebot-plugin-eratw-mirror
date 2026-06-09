from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


def _load_schedule_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "nonebot_plugin_eratw_mirror"
        / "schedule.py"
    )
    spec = importlib.util.spec_from_file_location("eratw_schedule", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_parse_daily_schedule():
    schedule = _load_schedule_module()
    spec = schedule.parse_schedule("daily@04:30")

    assert spec.trigger == "cron"
    assert spec.trigger_kwargs["hour"] == 4
    assert spec.trigger_kwargs["minute"] == 30


def test_parse_weekly_schedule():
    schedule = _load_schedule_module()
    spec = schedule.parse_schedule("weekly@mon,thu@03:30")

    assert spec.trigger == "cron"
    assert spec.trigger_kwargs["day_of_week"] == "mon,thu"
    assert spec.trigger_kwargs["hour"] == 3
    assert spec.trigger_kwargs["minute"] == 30


def test_parse_interval_days_schedule():
    schedule = _load_schedule_module()
    spec = schedule.parse_schedule("interval_days@2@03:30")

    assert spec.trigger == "interval"
    assert spec.trigger_kwargs["days"] == 2
    assert spec.trigger_kwargs["start_date"].hour == 3
    assert spec.trigger_kwargs["start_date"].minute == 30


def test_empty_schedule_disables_job():
    schedule = _load_schedule_module()

    assert schedule.parse_schedule("  ") is None


def test_invalid_schedule_raises():
    schedule = _load_schedule_module()

    with pytest.raises(ValueError):
        schedule.parse_schedule("weekly@funday@03:30")
