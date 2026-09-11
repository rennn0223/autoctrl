import base64
import struct
import zlib
from types import SimpleNamespace
import pytest
from autoctrl.domain import NavigationRequest, VisionRequest, MotionIntent, MotionKind
from autoctrl.sequence import SequentialInterpreter
from autoctrl.vision import encode_image, describe_image

@pytest.mark.parametrize('text', ['走八字，半徑 0.8 公尺', '繞八字', '/figure8'])
def test_ui_figure8(text):
    assert SequentialInterpreter().interpret(text) == NavigationRequest(radius_m=.8)


def test_ui_coordinates_are_not_split_as_motion_clauses():
    request = SequentialInterpreter().interpret('先到（0.7, 0），再到（1.4, 0.3）')
    assert request == NavigationRequest(points=((.7,0),(1.4,.3)))

@pytest.mark.parametrize('text', ['走八字，半徑 -1 公尺', '不要走八字', '走八字然後前進', '先到（1,2），再到（壞,4）', '走八字，半徑 nan 公尺'])
def test_invalid_whole_command_rejects(text):
    with pytest.raises(ValueError):
        SequentialInterpreter().interpret(text)


def test_stop_overrides_navigation():
    result = SequentialInterpreter().interpret('停止，走八字')
    assert isinstance(result, MotionIntent) and result.kind == MotionKind.STOP


def test_vision_has_no_motion_tools_and_handles_padded_bgr():
    assert isinstance(SequentialInterpreter().interpret('看看前面'), VisionRequest)
    frame = SimpleNamespace(width=1,height=1,step=4,encoding='bgr8',data=bytes([1,2,3,0]))
    png = base64.b64decode(encode_image(frame))
    offset = png.index(b'IDAT')
    size = struct.unpack('!I',png[offset-4:offset])[0]
    assert zlib.decompress(png[offset+4:offset+4+size]) == bytes([0,3,2,1])
    requests=[]
    def transport(payload):
        requests.append(payload)
        return {'message':{'content':'前方有方塊'}}
    assert describe_image(SimpleNamespace(model='test',_transport=transport),frame) == '前方有方塊'
    assert 'tools' not in requests[0]
