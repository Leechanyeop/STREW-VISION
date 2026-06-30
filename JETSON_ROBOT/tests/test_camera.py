from ai.detector.camera import MockVisionSource


def test_mock_camera_returns_payload():
    payload = MockVisionSource().read().to_payload()
    assert payload["label"] == "mock-object"
