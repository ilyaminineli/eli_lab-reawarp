"""Regression tests for the standalone M7 update script."""

import ast
from pathlib import Path


def test_update_script_uses_valid_text_newline_arguments():
    source = Path("apply_m7_update.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    newline_values = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "write_text":
            continue
        for keyword in node.keywords:
            if keyword.arg == "newline":
                assert isinstance(keyword.value, ast.Constant)
                newline_values.append(keyword.value.value)
    assert len(newline_values) == 2
    assert newline_values == ["\n", "\n"]
