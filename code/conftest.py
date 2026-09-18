from pathlib import Path


def pytest_configure(config):
    project_root = Path(__file__).resolve().parent.parent
    config.option.basetemp = str(project_root / "code" / ".pytest-tmp")
