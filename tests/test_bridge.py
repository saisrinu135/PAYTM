from app.routers.bridge import _langs


def test_owner_speech_goes_to_customer_language():
    assert _langs("te-IN", "hi-IN", "owner") == ("te-IN", "hi-IN")


def test_customer_speech_goes_to_owner_language():
    assert _langs("te-IN", "hi-IN", "customer") == ("hi-IN", "te-IN")
