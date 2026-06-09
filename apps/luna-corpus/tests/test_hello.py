"""Hello unit test module."""

from luna_corpus.hello import hello


def test_hello():
    """Test the hello function."""
    assert hello() == "Hello luna-corpus"
