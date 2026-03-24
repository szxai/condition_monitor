"""
简单的命令监听器，支持在后台线程中读取用户输入
"""
from __future__ import annotations

import threading
from queue import Queue, Empty
from typing import Optional


class CommandListener(threading.Thread):
    """后台读取命令输入"""

    def __init__(self, prompt: str = "cmd> "):
        super().__init__(daemon=True)
        self.prompt = prompt
        self._queue: Queue[str] = Queue()
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.is_set():
            try:
                command = input(self.prompt).strip()
            except EOFError:
                break
            if command:
                self._queue.put(command)

    def stop(self):
        self._stop_event.set()

    def get_next_command(self) -> Optional[str]:
        if self._queue.empty():
            return None
        try:
            return self._queue.get_nowait()
        except Empty:
            return None

