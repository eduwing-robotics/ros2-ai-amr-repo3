from aruco_detector_activation import activation_requested, set_activation


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
