import io
import unittest

from rich.console import Console

from autoctrl.console_ui import ConsoleUI
from autoctrl.pixel_pet import (
    PIXEL_PET_HEIGHT,
    PIXEL_PET_SPRITE,
    PIXEL_PET_WIDTH,
    render_pixel_pet,
)


class PixelPetTests(unittest.TestCase):
    def test_sprite_is_a_rectangular_19_by_17_grid(self) -> None:
        self.assertEqual(PIXEL_PET_WIDTH, 19)
        self.assertEqual(PIXEL_PET_HEIGHT, 17)
        self.assertTrue(all(len(row) == PIXEL_PET_WIDTH for row in PIXEL_PET_SPRITE))
        self.assertTrue(set("".join(PIXEL_PET_SPRITE)) <= set(".KDBT"))

    def test_high_fidelity_renderer_uses_full_background_cells(self) -> None:
        lines = [line.plain for line in render_pixel_pet().renderables]
        self.assertEqual(len(lines), PIXEL_PET_HEIGHT)
        self.assertEqual({len(line) for line in lines}, {47})
        glyphs = set("".join(lines))
        self.assertEqual(glyphs, {" ", " "})
        self.assertTrue(any(" " in line for line in lines))

    def test_narrow_terminal_hides_pixel_pet(self) -> None:
        output = io.StringIO()
        ui = ConsoleUI(
            Console(file=output, force_terminal=False, color_system=None, width=50)
        )
        ui.show_header(model="qwen3.6:35b", cmd_vel_topic="/small/cmd_vel")
        rendered = output.getvalue()
        self.assertNotIn("▀", rendered)
        self.assertNotIn("▄", rendered)

    def test_wide_colour_terminal_shows_pixel_pet(self) -> None:
        output = io.StringIO()
        ui = ConsoleUI(
            Console(
                file=output,
                force_terminal=True,
                color_system="truecolor",
                width=120,
                _environ={"TERM": "xterm-256color"},
            )
        )
        ui.show_header(model="qwen3.6:35b", cmd_vel_topic="/small/cmd_vel")
        rendered = output.getvalue()
        self.assertIn("\x1b[48;2;", rendered)
        self.assertIn("/small/cmd_vel", rendered)


if __name__ == "__main__":
    unittest.main()
