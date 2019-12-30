#! /usr/bin/env python3

"""
Proof of concept for simple pubsub system with Redis bridge.  this will be the messaging backbone of the next remote control system
"""

import os
import re
import time
import logging
import asyncio
import aioredis
from collections import namedtuple
from sshtunnel import SSHTunnelForwarder

from aiotools import patch, wait_gracefully


Message = namedtuple("Message", "source, key, value")

logger = logging.getLogger(__name__)
# logger = logging.getLogger()


def ts():
    return time.time()


class RegexPattern:
    """ regex patterns """

    def __init__(self, pattern):
        self.pattern = pattern
        self.regex = re.compile(pattern)

    def match(self, subject):
        return self.regex.fullmatch(subject)

    def __str__(self):
        return self.pattern


class DotPattern:
    """ dot-separated path-style patterns """

    def __init__(self, pattern):
        self.pattern = pattern

    def match(self, subject):
        if self.pattern.upper() == subject.upper() or self.pattern in ("", "."):
            return True

        prefix = self.pattern + "" if self.pattern[-1] == "." else "."
        return subject.upper().startswith(prefix.upper())

    def __str__(self):
        return self.pattern


class MessageBus:
    """ MessageBus interface """

    def __init__(self):
        self._channels = {}

    def set_channel(self, key, value):
        self._channels[key] = value

    def get_channels(self):
        return self._channels.items()


class BasicMessageBus(MessageBus):
    """ Basic MessageBus implementation """

    def __init__(self):
        super().__init__()
        self.conn = None
        self.listeners = set()

    async def connect(self, address=None):
        self.conn = self
        logger.info(f"bus connected ({address})")

    async def send(self, message):
        if not self.conn:
            raise RuntimeError("bus not connected")

        if message.key.endswith("."):
            raise ValueError("trailing '.' in key")
            
        self.set_channel(message.key, message.value)
        for pattern, q in self.listeners:
            if pattern.match(message.key):
                await q.put(message)

    async def listen(self, pattern):
        if not self.conn:
            raise RuntimeError("bus not connected")

        try:
            p = DotPattern(pattern)
            q = asyncio.Queue()

            self.listeners.add((p, q))

            # yield current values
            for k, v in self.get_channels():
                if p.match(k):
                    yield Message("local", k, v)

            # yield the messages as they come through
            while True:
                msg = await q.get()
                if not msg:
                    break
                yield msg
        except:
            raise
        finally:
            self.listeners.remove((p, q))

    async def status(self):
        if self.conn:
            return {
                "status": "connected",
                "listeners": [str(p) for p, _ in self.listeners],
                "channels": list(self.get_channels()),
                "timestamp": ts(),
            }
        else:
            return {"status": "disconnected"}

    async def close(self):
        self.conn = None
        for p, q in self.listeners:
            await q.put(None)
        logger.info(f"connection closed")


class MessageBridge:
    """ bridge the local bus with an external bus such as redis """

    def __init__(self, pattern, tunnel_config, bus):
        self.pattern = pattern
        self.tunnel_config = tunnel_config
        self.bus = bus

    async def _receiver(self, aredis):
        redis_pattern = self.pattern
        if redis_pattern.endswith('.'):
            redis_pattern += '*'

        try:
            chan, = await aredis.psubscribe(redis_pattern)
            while await chan.wait_message():
                k, v = await chan.get(encoding="utf-8")
                logger.info(f"bridge in {self.pattern}: message {k}: {v}")
                await self.bus.send(Message("redis", k.decode(), v))
        except asyncio.CancelledError:
            logger.info(f"bridge in {self.pattern}: cancelled")
        finally:
            await aredis.punsubscribe(redis_pattern)

    async def _sender(self, aredis):
        """ route local messages to redis """

        try:
            async for message in self.bus.listen(self.pattern):
                if message.source != "redis":
                    logger.info(f"bridge out {self.pattern}: {message}")
                    await aredis.publish(message.key, message.value)
        except asyncio.CancelledError:
            logger.info(f"bridge out {self.pattern}: cancelled")

    async def start(self):
        """ open tunnel to redis server and start sender/receiver tasks """

        with SSHTunnelForwarder(**self.tunnel_config) as tunnel:
            address = tunnel.local_bind_address
            aredis = await aioredis.create_redis_pool(address, encoding="utf-8")
            logger.info(f"bridge connected: {aredis.address}")

            try:
                await asyncio.gather(
                    self._receiver(aredis),
                    self._sender(aredis),
                )
            except asyncio.CancelledError:
                logger.info(f"bridge start {self.pattern}: cancelled")
            except Exception as e:
                logger.info(f'bridge start {self.pattern}: exception {e} {type(e)}')

            aredis.close()
            await aredis.wait_closed()


async def main():
    """ main synchronous entry point """

    async def talk(bus, keys):
        """ generate some test messages """

        for v in range(5):
            for k in keys:
                await asyncio.sleep(0.35)
                await bus.send(Message("local", k, v))

    async def listen(bus, pattern):
        await asyncio.sleep(1.5)
        try:
            async for x in bus.listen(pattern):
                print(f"listen({pattern}):", x)
        except asyncio.CancelledError:
            pass

    async def monitor():
        """ echo bus status every 2 sec """

        for n in range(6):
            await asyncio.sleep(2)
            print("monitor status:", n, await ps.status())

    ps = BasicMessageBus()
    await ps.connect()

    tunnel_config = {
        "ssh_address_or_host": ("robnee.com", 22),
        "remote_bind_address": ("127.0.0.1", 6379),
        "local_bind_address": ("127.0.0.1",),
        "ssh_username": "rnee",
        "ssh_pkey": os.path.expanduser(r"~/.ssh/id_rsa"),
    }
    bridge = MessageBridge("cat.", tunnel_config, ps)

    aws = (
        talk(ps, ("cat.dog", "cat.pig", "cow.emu")),
        listen(ps, "."),
        listen(ps, "cat."),
        listen(ps, "cat.pig"),
        bridge.start(),
        monitor(),
    )
    tasks = [asyncio.create_task(c) for c in aws]
    await wait_gracefully(tasks, timeout=15)

    await ps.close()
    
    print("main: done")


if __name__ == "__main__":
    patch()
    logger.setLevel(logging.WARNING)
    handler = logging.StreamHandler()
    try:
        logger.addHandler(handler)
        asyncio.run(main(), debug=True)
    finally:
        logger.removeHandler(handler)
    print("all: done")
