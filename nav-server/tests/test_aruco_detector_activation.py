from nav_app.services.aruco_detector_activation import activation_requested, processing_due, set_activation


def test_activation_file_is_off_by_default_and_tracks_dock_scope(tmp_path):
    activation_file = tmp_path / "tb3_burger_02.enabled"

    assert activation_requested(activation_file, default=False) is False

    assert set_activation(activation_file, True) is True
    assert activation_requested(activation_file, default=False) is True

    assert set_activation(activation_file, False) is True
    assert activation_requested(activation_file, default=False) is False


def test_empty_activation_path_keeps_standalone_default():
    assert activation_requested("", default=True) is True
    assert activation_requested("", default=False) is False
    assert set_activation("", True) is False


def test_processing_due_caps_detection_without_delaying_the_first_frame():
    assert processing_due(0.0, 10.0, 5.0) is True
    assert processing_due(10.0, 10.19, 5.0) is False
    assert processing_due(10.0, 10.20, 5.0) is True
    assert processing_due(10.0, 10.01, 0.0) is True
