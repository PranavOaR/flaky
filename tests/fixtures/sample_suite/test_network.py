"""Always-failing fake network test to demonstrate the network classifier.

Does not actually open a socket — raises an error whose message matches
the network keyword set.
"""


def test_fake_network_call():
    raise ConnectionError("connection refused to api.example.com (HTTP 503)")
