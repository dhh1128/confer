import confer


def test_package_importable_with_version():
    assert confer.__version__ == "0.1.0"
