
"""
message bus classes
"""

import time
from collections import namedtuple

Message = namedtuple("Message", "key, value, ts")


def ts():
    return time.time()


class MessageBus:
    def __init__(self):
        self._channels = {}
        self.start_time = ts()

    def set_channel(self, k, v):
        self._channels[k] = v

    def get_channels(self):
        return self._channels.items()

    @staticmethod
    def new_message(k, v):
        return Message(k, v, ts())


