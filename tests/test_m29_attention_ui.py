from __future__ import annotations

import os
from fractions import Fraction

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from reawarp.score import AttentionSpan, MusicalEvent, OrchestrationPlan, Score
from reawarp.ui.pages.attention_map import AttentionMapPage


_APP = None


def _application():
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication([])
        app = _APP
    return app


def test_attention_map_edits_rational_spans_and_focus_recede_without_audio_gain():
    _application()
    page = AttentionMapPage()
    page.set_score(Score())
    plans = []
    page.planChanged.connect(plans.append)

    page.role.setCurrentText("melody")
    page.start_beats.setText("1/4")
    page.end_beats.setText("13/4")
    page.depth.setCurrentIndex(page.depth.findData("midground"))
    page.attention_role.setCurrentIndex(page.attention_role.findData("motif"))
    page.register_low.setText("48")
    page.register_high.setText("72")
    page.spectral_band.setText("mid")
    page.onset_density.setText("0.5")
    page.save_span_button.click()

    assert len(plans) == 1
    plan = OrchestrationPlan.from_dict(plans[0])
    span = plan.attention[0]
    assert span.start_beats == Fraction(1, 4)
    assert span.end_beats == Fraction(13, 4)
    assert span.depth == "midground"
    assert span.attention_role == "motif"
    assert span.register_low == 48
    assert span.onset_density == pytest.approx(0.5)

    page.focus_button.click()
    focused = OrchestrationPlan.from_dict(plans[-1]).attention[0]
    assert focused.depth == "foreground"
    assert focused.prominence == pytest.approx(0.85)
    page.recede_button.click()
    receded = OrchestrationPlan.from_dict(plans[-1]).attention[0]
    assert receded.depth == "background"
    assert receded.prominence == pytest.approx(0.70)
    assert receded.register_low == 48
    page.close()


def test_attention_map_explains_conflicts_and_records_human_disposition():
    _application()
    plan = OrchestrationPlan(attention=(
        AttentionSpan(
            "melody", 0, 4, "foreground", attention_role="motif",
            register_low=48, register_high=72, spectral_band="mid",
        ),
        AttentionSpan(
            "break", 1, 3, "background", attention_role="counter_rhythm",
            register_low=60, register_high=84, spectral_band="mid",
        ),
    ))
    page = AttentionMapPage()
    page.set_score(Score(orchestration_plan=plan.to_dict()))
    assert page.diagnostics.count() == 1
    assert "overlapping register ranges" in page.diagnostics.item(0).text()
    assert "shared spectral zone: mid" in page.diagnostics.item(0).text()

    reviews = []
    page.reviewRequested.connect(reviews.append)
    page.review_disposition.setCurrentIndex(
        page.review_disposition.findData("useful")
    )
    page.review_notes.setPlainText("The layers intentionally fuse into one noisy object.")
    page.review_button.click()
    assert reviews[0]["disposition"] == "useful"
    assert reviews[0]["notes"].startswith("The layers intentionally fuse")
    assert reviews[0]["warning"]["kind"] == "attention_competition"
    page.close()


def test_attention_map_estimates_symbolic_descriptors_and_exposes_translation_checks():
    _application()
    score = Score(events=(
        MusicalEvent(
            "note-1", "melody", 0, Fraction(1, 2),
            kind="note", pitch=60, velocity=0.8,
        ),
        MusicalEvent(
            "note-2", "melody", 1, Fraction(1, 2),
            kind="note", pitch=64, velocity=0.6,
        ),
    ), orchestration_plan=OrchestrationPlan(attention=(
        AttentionSpan("melody", 0, 2, "foreground", attention_role="motif"),
    )).to_dict())
    page = AttentionMapPage()
    page.set_score(score)

    plans = []
    checks = []
    page.planChanged.connect(plans.append)
    page.translationCheckRequested.connect(checks.append)
    page.estimate_button.click()
    estimated = OrchestrationPlan.from_dict(plans[-1]).attention[0]
    assert estimated.onset_density == pytest.approx(1.0)
    assert estimated.register_low == 60
    assert estimated.register_high == 64
    assert estimated.prominence == pytest.approx(0.7)

    page.mono_button.click()
    page.low_volume_button.click()
    assert checks == ["mono", "low_volume"]
    page.close()
