import json
import numpy as np
import pytest
from camera_calibration import load_calibration

def test_load_calibration(tmp_path):
    path=tmp_path/'camera.json';path.write_text(json.dumps({'camera_matrix':[[300,0,160],[0,301,120],[0,0,1]],'dist_coeffs':[.1,-.2,0,0,.05],'image_width':320}))
    matrix,distortion,metadata=load_calibration(str(path))
    assert matrix.shape==(3,3) and distortion.shape==(5,) and metadata['image_width']==320

@pytest.mark.parametrize('matrix',[[],[1]*9,[[1,0],[0,1]]])
def test_rejects_invalid_matrix(tmp_path,matrix):
    path=tmp_path/'bad.json';path.write_text(json.dumps({'camera_matrix':matrix,'dist_coeffs':[0]*5}))
    with pytest.raises(ValueError,match='camera_matrix'):load_calibration(str(path))

def test_rejects_non_finite(tmp_path):
    path=tmp_path/'bad.json';path.write_text(json.dumps({'camera_matrix':[[np.nan,0,160],[0,300,120],[0,0,1]],'dist_coeffs':[0]*5}))
    with pytest.raises(ValueError,match='non-finite'):load_calibration(str(path))
