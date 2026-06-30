from ai.detector.validator import is_valid_detection


def test_detection_validator_requires_label():
    assert is_valid_detection({"label": "RED"})
    assert not is_valid_detection({"label": None})
