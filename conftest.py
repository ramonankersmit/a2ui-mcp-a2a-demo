from pathlib import Path
import sys


def pytest_configure() -> None:
    repo_root = Path(__file__).resolve().parent
    a2ui_src = repo_root / "a2a_agents/python/a2ui_extension/src"
    if a2ui_src.exists():
        sys.path.insert(0, str(a2ui_src))
