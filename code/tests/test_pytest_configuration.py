from pathlib import Path


def test_pytest_uses_the_repository_test_temp_directory(pytestconfig):
    project_root = Path(__file__).parents[2]
    configured_options = pytestconfig.getini("addopts")
    configured_base_temp = Path(pytestconfig.getoption("basetemp")).resolve()
    expected_base_temp = project_root / "code" / ".pytest-tmp"

    assert "--basetemp=code/.pytest-tmp" in configured_options
    assert pytestconfig.getini("cache_dir") == "code/.pytest-tmp/.pytest_cache"
    assert configured_base_temp == expected_base_temp
    assert (project_root / "pytest.ini").is_file()
