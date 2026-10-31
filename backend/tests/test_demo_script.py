"""The scripted live demo (docs/LIVE_DEMO.md) runs end to end: order, shortage, alert, transfer, approval, WMS, stock.

scripts/demo_run.py is what a presenter runs; this runs the same code against the app in-process, so the demo
cannot rot unnoticed.
"""
import sys
from pathlib import Path

import pytest

from app.core.config import settings

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from demo_run import Demo  # noqa: E402


def run_story(client, webhook_key=""):
    said = []
    facts = Demo(client, say=said.append, webhook_key=webhook_key).run()
    return facts, "\n".join(said)


def test_the_story_runs_end_to_end_with_a_manual_confirmation(anon):
    facts, said = run_story(anon)
    assert facts["short"] > 0
    assert facts["final_stock"] == pytest.approx(facts["dest_after_receive"] - facts["sent_qty"], abs=0.01)
    assert "Done." in said


def test_the_story_runs_end_to_end_with_the_wms_webhook(anon, monkeypatch):
    monkeypatch.setattr(settings, "integration_webhook_key", "demo-key")
    facts, said = run_story(anon, webhook_key="demo-key")
    assert "Pushed by the WMS to the webhook" in said
    assert facts["final_stock"] == pytest.approx(facts["dest_after_receive"] - facts["sent_qty"], abs=0.01)
