import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from reawarp.synthesis.sound_object import SoundObjectLayer, SoundObjectPatch, SoundObjectSource
from reawarp.ui.pages.sound_object_editor import SoundObjectEditorPage


_APP = None


def _application():
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication([])
        app = _APP
    return app


def _patch():
    source = SoundObjectSource(
        "osc", source_kind="procedural", sample_rate=8_000, source_model="sine",
    )
    layer = SoundObjectLayer("body", "body", "osc", 0, 512, gain=0.4)
    return SoundObjectPatch(
        patch_id="ui-sound-object", name="UI Sound Object",
        sample_rate=8_000, seed=2,
        source_identity_id="source:ui", processing_identity_id="processing:ui",
        sources=(source,), layers=(layer,),
    )


def test_editor_edits_layer_and_emits_save_and_layer_audition():
    _application()
    page = SoundObjectEditorPage()
    patch = _patch()
    page.set_patches([patch])
    page.layer_role.setCurrentIndex(page.layer_role.findData("tail"))
    page.gain.setValue(0.8)
    saved, auditions = [], []
    page.saveRequested.connect(saved.append)
    page.auditionRequested.connect(lambda item, layer: auditions.append((item, layer)))
    page.save_button.click()
    assert saved[0].layers[0].role == "tail"
    assert saved[0].layers[0].gain == pytest.approx(0.8)
    page.audition_layer_button.click()
    assert auditions[0][0].layers[0].role == "tail"
    assert auditions[0][1] == "body"
    page.close()
