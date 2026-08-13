from __future__ import annotations

from rich.color import Color
from rich.console import Group
from rich.style import Style
from rich.text import Text


PIXEL_PET_PALETTE: dict[str, tuple[int, int, int]] = {
    "K": (5, 4, 3),
    "D": (64, 35, 22),
    "B": (97, 54, 34),
    "T": (185, 114, 49),
}

PIXEL_PET_SPRITE: tuple[str, ...] = (
    "...........KKKKK...",
    "..........KDBBBBK..",
    "........KKBBBBBBBK.",
    ".......KBBBKBTBBTDK",
    "......KBBDBKBKBBKDK",
    ".BK...KDDDDKBKBBKDK",
    "KK.....KDDDKBBBBBBK",
    "KK.....KDDDKTTTTKKK",
    "KBKKKKKKKDDKBKTTTTK",
    ".KDBBBBBDKKDBBKKKK.",
    ".KBBBBBBBBBBBBBK...",
    ".KBBBBBBBBBBTBTK...",
    ".KBBBBBBBBBTTTBK...",
    "KBBTBBBDKBBKTKKK...",
    "KTTKKBKKKBTKKDKK...",
    "KTK.KKK.KTTKKBTK...",
    "KKK.....KKKK.KKK...",
)

PIXEL_PET_WIDTH = len(PIXEL_PET_SPRITE[0])
PIXEL_PET_HEIGHT = len(PIXEL_PET_SPRITE)
PIXEL_PET_COLUMN_WIDTHS = tuple(2 if x % 2 == 0 else 3 for x in range(PIXEL_PET_WIDTH))
PIXEL_PET_RENDER_WIDTH = sum(PIXEL_PET_COLUMN_WIDTHS)
PIXEL_PET_MONOCHROME = {
    "K": "█",
    "D": "▓",
    "B": "▒",
    "T": "░",
}


def render_pixel_pet(*, monochrome: bool = False) -> Group:
    """以完整背景色終端格呈現 19×17 PixPet，避免字型半格產生接縫。"""
    lines: list[Text] = []
    for row in PIXEL_PET_SPRITE:
        line = Text()
        for key, width in zip(row, PIXEL_PET_COLUMN_WIDTHS, strict=True):
            rgb = PIXEL_PET_PALETTE.get(key)
            if rgb is None:
                line.append(" " * width)
            elif monochrome:
                line.append(PIXEL_PET_MONOCHROME[key] * width)
            else:
                line.append(
                    " " * width,
                    style=Style(bgcolor=Color.from_rgb(*rgb)),
                )
        lines.append(line)
    return Group(*lines)
