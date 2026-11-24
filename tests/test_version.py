"""Public package and engine version consistency."""
from reawarp import __version__
from reawarp.core.engine import ReawarpEngine


def test_release_version_is_080():
    assert __version__ == "0.8.0"
    assert ReawarpEngine.VERSION == "0.8.0"
