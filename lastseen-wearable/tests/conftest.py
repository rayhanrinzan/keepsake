"""Pytest setup. Tests marked `models` load real YOLO/CLIP weights and are skipped unless
`--run-models` is passed (`pytest --run-models tests/manual`)."""
import pytest


def pytest_addoption(parser):
    parser.addoption("--run-models", action="store_true", default=False,
                     help="run tests that load real ML models")


def pytest_configure(config):
    config.addinivalue_line("markers", "models: loads real ML models (needs --run-models)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-models"):
        return
    skip = pytest.mark.skip(reason="needs --run-models")
    for item in items:
        if "models" in item.keywords:
            item.add_marker(skip)
