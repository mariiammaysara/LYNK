"""Foundation smoke test — package imports and version is set."""

import rel_mcp


def test_package_imports() -> None:
    assert rel_mcp.__version__ == "0.1.0"
