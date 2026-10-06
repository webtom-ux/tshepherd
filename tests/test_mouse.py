import curses
from pathlib import Path
import queue
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import tshepherd as app
from fixtures import sample_snapshot


class MouseTests(unittest.TestCase):
    def setUp(self):
        app.set_language('en')
        self.snapshot = sample_snapshot(str(Path.cwd()))
        self.view = app.View(snapshot=self.snapshot, last_success=time.time())
        self.rows = [app.PrimaryRow()] + app.rows_for(self.snapshot, {}, time.time(), 45)
        self.mouse = app.MouseSelection()

    def frame(self, width=110, height=30):
        hits = {}
        lines = app.render_lines(self.view, self.rows, width, height, False, time.time(), hits)
        return lines, hits

    def press(self, hits, y, now=1, size=(30, 110), pressed=True):
        return self.mouse.click((0, 12, y, pressed), hits, size, self.view, self.rows, now)

    def test_single_click_selects_exact_rendered_worker_and_primary(self):
        for width in (45, 110):
            lines, hits = self.frame(width)
            for y, key in hits.items():
                self.mouse.reset()
                self.assertFalse(self.press(hits, y, size=(30, width)))
                self.assertEqual(self.view.selected, key)
                selected_frame, _ = self.frame(width)
                self.assertTrue(any('>' in text for text, _ in selected_frame))
            for y in set(range(30)) - set(hits):
                before = self.view.selected
                self.assertFalse(self.press(hits, y, size=(30, width)))
                self.assertEqual(before, self.view.selected)

    def test_double_click_same_identity_once_and_release_is_not_activation(self):
        _, hits = self.frame()
        y = next(y for y, key in hits.items() if key != self.rows[0].key)
        self.assertFalse(self.press(hits, y))
        self.assertFalse(self.press(hits, y, 1.05, pressed=False))
        self.assertTrue(self.press(hits, y, 1.1))
        self.assertFalse(self.press(hits, y, 1.2))  # Triple click does not focus twice.
        self.assertFalse(self.press(hits, y, 2))

    def test_different_entry_refresh_physical_change_resize_and_blank_cancel_pair(self):
        _, hits = self.frame()
        y, other = list(hits)[:2]
        self.assertFalse(self.press(hits, y))
        self.assertFalse(self.press(hits, other, 1.1))
        self.mouse.reset()
        self.press(hits, y)
        self.view.apply('snapshot', (self.snapshot, {}))
        self.assertFalse(self.press(hits, y, 1.1))
        self.mouse.reset()
        self.press(hits, y)
        self.view.natives[hits[y][0]] = app.Native(physical=('new', 'tab', 'terminal'))
        self.assertFalse(self.press(hits, y, 1.1))
        self.mouse.reset()
        self.press(hits, y)
        self.assertFalse(self.press(hits, y, 1.1, size=(31, 110)))
        self.mouse.reset()
        self.press(hits, y)
        self.press(hits, 0, 1.05)
        self.assertFalse(self.press(hits, y, 1.1))
        self.rows = [row for row in self.rows if row.key != hits[y]]
        self.assertFalse(self.press(hits, y, 1.2))

    def test_scrolled_narrow_detail_and_small_window_hit_map(self):
        self.view.offset = 3
        lines, hits = self.frame(45, 18)
        self.assertGreater(self.view.offset, 0)
        for y, key in hits.items():
            row = next(row for row in self.rows if row.key == key)
            if isinstance(row, app.PrimaryRow):
                self.assertTrue('Firstmate' in lines[y][0] or 'unavailable' in lines[y][0])
            else:
                self.assertTrue(row.title in lines[y][0] or 'task' in lines[y][0])
        _, hits = self.frame(27, 15)
        self.assertEqual(hits, {})

    def run_tui(self, keys):
        screen = Mock()
        screen.getmaxyx.return_value = (30, 110)
        screen.getch.side_effect = keys
        poller = Mock()
        poller.results = queue.Queue()
        poller.busy.is_set.return_value = False
        source = SimpleNamespace(config=SimpleNamespace(interval=5, ttl=45))
        writes = []
        with patch.object(app, 'Poller', return_value=poller), \
                patch.object(app, 'overview_rows', return_value=self.rows), \
                patch.object(app, 'terminal_write', side_effect=writes.append), \
                patch.object(app.curses, 'curs_set'), \
                patch.object(app.curses, 'has_colors', return_value=False):
            try:
                app.tui(screen, source)
            finally:
                self.assertEqual(writes, [app.MouseSelection.enable, app.MouseSelection.disable])
                poller.close.assert_called_once()
        return poller

    def row_y(self, row):
        _, hits = self.frame()
        return next(y for y, key in hits.items() if key == row.key)

    def test_tui_mouse_and_keyboard_share_dispatch_and_restore_reporting(self):
        y = self.row_y(self.rows[1])
        poller = self.run_tui(sgr(0, 12, y) + sgr(0, 12, y, 'm') + sgr(0, 12, y)
                              + [curses.KEY_DOWN, curses.KEY_ENTER, ord('q')])
        self.assertEqual([c.args for c in poller.request_focus.call_args_list],
                         [(self.rows[1].key, ()), (self.rows[2].key, ())])

    def test_tui_vertical_wheel_moves_selection_sideways_does_not(self):
        y = self.row_y(self.rows[1])
        poller = self.run_tui(sgr(0, 12, y) + sgr(65, 12, y) + sgr(0, 12, y)  # Wheel breaks the pair.
                              + sgr(65, 12, y) + sgr(69, 12, y)  # Shift+wheel still scrolls.
                              + sgr(66, 12, y) + sgr(67, 12, y)  # Sideways scroll is ignored.
                              + sgr(64, 12, y) + [curses.KEY_ENTER, ord('q')])
        poller.request_focus.assert_called_once_with(self.rows[2].key, ())

    def test_decode_fragmented_sgr_legacy_reports_and_plain_keys(self):
        mouse = app.MouseSelection()
        results = [mouse.decode(k) for k in sgr(0, 12, 5)[:4] + [-1, -1] + sgr(0, 12, 5)[4:]]
        self.assertEqual([r for r in results if r is not None], [(0, 12, 5, True)])
        self.assertEqual([mouse.decode(k) for k in sgr(65, 300, 5, 'm')][-1], (65, 300, 5, False))
        # keypad() reports the legacy "ESC [ M" prefix as KEY_MOUSE; payload bytes never leak.
        for code, pressed in ((0, True), (3, False), (65, True), (67, True)):
            results = [mouse.decode(k) for k in (curses.KEY_MOUSE, 32 + code, 33 + 12, 33 + 5)]
            self.assertEqual(results, [None, None, None, (code, 12, 5, pressed)])
        self.assertEqual([mouse.decode(k) for k in (27, -1, ord('q'))], [None, None, ord('q')])
        self.assertEqual([mouse.decode(k) for k in (27, curses.KEY_UP)], [None, curses.KEY_UP])
        self.assertEqual([mouse.decode(k) for k in (-1, ord('j'), curses.KEY_ENTER)],
                         [-1, ord('j'), curses.KEY_ENTER])

    def test_mouse_reporting_restored_on_input_failure(self):
        with self.assertRaisesRegex(RuntimeError, 'input failed'):
            self.run_tui(RuntimeError('input failed'))


def sgr(code, x, y, final='M'):
    return [ord(c) for c in f'\x1b[<{code};{x + 1};{y + 1}{final}']


if __name__ == '__main__':
    unittest.main()
