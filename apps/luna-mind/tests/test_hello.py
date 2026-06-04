"""Hello unit test module."""

from apps/luna_mind.hello import hello


def test_hello():
    """Test the hello function."""
    assert hello() == "Hello apps/luna-mind"
