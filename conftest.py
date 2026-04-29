collect_ignore_glob = []

# Prevent pytest from trying to collect autopsy dataclasses as test classes
def pytest_configure(config):
    config.addinivalue_line(
        "filterwarnings", "ignore::pytest.PytestCollectionWarning"
    )
