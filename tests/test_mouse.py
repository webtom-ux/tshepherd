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

    def press(self, hits, y, now=1, size=(30, 110), buttons=curses.BUTTON1_PRESSED):
        return self.mouse.click((0, 12, y, 0, buttons), hits, size, self.view, self.rows, now)

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
        self.assertFalse(self.press(hits, y, 1.05, buttons=curses.BUTTON1_RELEASED))
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

    def test_tui_mouse_and_keyboard_share_dispatch_and_restore_reporting(self):
        _, hits = self.frame()
        y = next(y for y, key in hits.items() if key == self.rows[1].key)
        target = hits[y]
        screen = Mock()
        screen.getmaxyx.return_value = (30, 110)
        screen.getch.side_effect = [curses.KEY_MOUSE, curses.KEY_MOUSE,
                                   curses.KEY_DOWN, curses.KEY_ENTER, ord('q')]
        poller = Mock()
        poller.results = queue.Queue()
        poller.busy.is_set.return_value = False
        source = SimpleNamespace(config=SimpleNamespace(interval=5, ttl=45))
        with patch.object(app, 'Poller', return_value=poller), \
                patch.object(app, 'overview_rows', return_value=self.rows), \
                patch.object(app.curses, 'curs_set'), \
                patch.object(app.curses, 'has_colors', return_value=False), \
                patch.object(app.curses, 'mousemask', return_value=(1, 42)) as mask, \
                patch.object(app.curses, 'mouseinterval', return_value=166) as interval, \
                patch.object(app.curses, 'getmouse', return_value=(0, 12, y, 0, curses.BUTTON1_PRESSED)):
            app.tui(screen, source)
        self.assertEqual(poller.request_focus.call_count, 2)
        self.assertEqual(poller.request_focus.call_args_list[0].args, (target, ()))
        self.assertEqual(poller.request_focus.call_args_list[1].args, (self.rows[2].key, ()))
        self.assertEqual(mask.call_args.args, (42,))
        self.assertEqual(interval.call_args.args, (166,))
        poller.close.assert_called_once()

    def test_tui_wheel_moves_selection_like_arrows_and_breaks_click_pair(self):
        _, hits = self.frame()
        y = next(y for y, key in hits.items() if key == self.rows[1].key)
        press = (0, 12, y, 0, curses.BUTTON1_PRESSED)
        down = (0, 12, y, 0, app.MouseSelection.wheel_down)
        up = (0, 12, y, 0, curses.BUTTON4_PRESSED)
        screen = Mock()
        screen.getmaxyx.return_value = (30, 110)
        screen.getch.side_effect = [curses.KEY_MOUSE] * 6 + [curses.KEY_ENTER, ord('q')]
        poller = Mock()
        poller.results = queue.Queue()
        poller.busy.is_set.return_value = False
        source = SimpleNamespace(config=SimpleNamespace(interval=5, ttl=45))
        with patch.object(app, 'Poller', return_value=poller), \
                patch.object(app, 'overview_rows', return_value=self.rows), \
                patch.object(app.curses, 'curs_set'), \
                patch.object(app.curses, 'has_colors', return_value=False), \
                patch.object(app.curses, 'mousemask', return_value=(1, 42)) as mask, \
                patch.object(app.curses, 'mouseinterval', return_value=166), \
                patch.object(app.curses, 'getmouse', side_effect=[press, down, press, down, down, up]):
            app.tui(screen, source)
        wheel = curses.BUTTON4_PRESSED | app.MouseSelection.wheel_down
        self.assertEqual(mask.call_args_list[0].args[0] & wheel, wheel)
        poller.request_focus.assert_called_once_with(self.rows[2].key, ())

    def test_mouse_reporting_restored_on_input_failure(self):
        screen = Mock()
        screen.getmaxyx.return_value = (30, 110)
        screen.getch.side_effect = RuntimeError('input failed')
        poller = Mock()
        poller.results = queue.Queue()
        source = SimpleNamespace(config=SimpleNamespace(interval=5, ttl=45))
        with patch.object(app, 'Poller', return_value=poller), \
                patch.object(app.curses, 'curs_set'), \
                patch.object(app.curses, 'has_colors', return_value=False), \
                patch.object(app.curses, 'mousemask', return_value=(1, 42)) as mask, \
                patch.object(app.curses, 'mouseinterval', return_value=166) as interval:
            with self.assertRaisesRegex(RuntimeError, 'input failed'):
                app.tui(screen, source)
        self.assertEqual(mask.call_args.args, (42,))
        self.assertEqual(interval.call_args.args, (166,))
        poller.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
