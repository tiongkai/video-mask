"""
gui_helpers.py — Non-GUI utilities used by gui.py.

Kept separate from gui.py so they can be tested without a display.
"""

import queue


class QueueWriter:
    """File-like object that puts written text into a queue.

    Used to redirect sys.stdout from a background thread into a
    tkinter Text widget via a queue-drain polling loop.
    """

    def __init__(self, q: queue.Queue):
        self._q = q

    def write(self, text: str) -> int:
        self._q.put(text)
        return len(text)

    def flush(self):
        pass  # no-op — required by the sys.stdout protocol
