import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from reawarp.ui.pages.variations import VariationBrowserPage


_APP = None


def _application():
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication([])
        app = _APP
    return app


def test_m32_variation_page_emits_context_decisions_and_human_report():
    _application()
    page = VariationBrowserPage()
    page.set_stems(["kick", "snare", "melody"])
    page.set_phrase_choices([("phrase-a", "phrase-a · PRESENTATION")])
    page.m32_context.setCurrentIndex(page.m32_context.findData("reduced_density"))
    page.m32_subtraction_percent.setValue(40)
    page.m32_roles.item(0).setCheckState(2)
    requested, decisions, notes = [], [], []
    page.m32ContextRequested.connect(requested.append)
    page.m32DecisionRequested.connect(decisions.append)
    page.m32ReportRequested.connect(notes.append)

    page.m32_build_button.click()
    assert requested[0]["context"] == "reduced_density"
    assert requested[0]["subtraction_percent"] == 40
    assert requested[0]["roles"] == ["kick"]
    page.m32_keep_button.click()
    page.m32_restore_button.click()
    assert decisions == ["keep", "restore"]

    page._m32_report_fields["identity"].setText("The motif remains audible.")
    page.m32_report_save_button.click()
    assert notes[0]["identity"] == "The motif remains audible."
    assert set(notes[0]) == {
        "identity", "continuity", "contrast", "legibility", "motif_development",
        "orchestration", "pacing", "surprise", "emotional_coherence", "technical_integrity",
    }
    page.close()
