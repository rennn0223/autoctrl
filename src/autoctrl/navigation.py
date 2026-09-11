"""High-level UI requests, parsed completely before any vehicle action."""
from __future__ import annotations
import re
from .domain import NavigationRequest, VisionRequest

_NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)'
_PAIR = rf'[（(]\s*({_NUMBER})\s*[,，]\s*({_NUMBER})\s*[）)]'


def interpret_navigation(text: str):
    text = text.strip()
    if text in ('/look', '看看前面', '看一下前面', '你看到了什麼', '你看到了什麼？', '描述眼前畫面'):
        return VisionRequest()
    match = re.fullmatch(rf'(?:請)?(?:走|繞)(?:個|一個)?八字(?:[，, ]*半徑\s*({_NUMBER})\s*(?:公尺|米|m))?[。！! ]*', text)
    if match:
        return NavigationRequest(radius_m=float(match[1]) if match[1] else .8)
    if text == '/figure8':
        return NavigationRequest(radius_m=.8)
    waypoint = re.fullmatch(rf'(?:請)?(?:先)?(?:到|走到|繞到|導航到)\s*{_PAIR}(?:\s*(?:公尺|米|m))?(?:\s*[,，]?\s*(?:然後|接著|再)\s*(?:到|走到|繞到|導航到)\s*{_PAIR}(?:\s*(?:公尺|米|m))?)*[。!！ ]*', text)
    if waypoint:
        return NavigationRequest(points=tuple((float(x), float(y)) for x,y in re.findall(_PAIR,text)))
    if '八字' in text or re.search(r'(?:到|導航).*?[（(]', text) or text.startswith(('/figure8', '/look')):
        raise ValueError('請完整輸入：走八字，半徑 0.8 公尺；或先到（0.7, 0），再到（1.4, 0.3）。看圖請輸入「看看前面」。')
    return None
