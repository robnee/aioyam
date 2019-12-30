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

    async def send(self, message):
        pass

    async def listen(self, pattern):
        pass

    async def close(self):
        pass


class BasicMessageBus(MessageBus):
    """ Basic MessageBus implementation """

    def __init__(self):
        super().__init__()
        self.conn = None
        self._channels = {}
        self.listeners = set()

    def set_channel(self, key, value):
        self._channels[key] = value

    def get_channels(self):
        return self._channels.items()

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


# todo: should this be initialized with a mask to restrict the namespace?
# todo: using patterns makes many of the status metrics unavailable.  Should there just be a single channel?
class RedisMessageBus(MessageBus):
    """ A MessageBus implemented as a Redis pubsub channel """

    def __init__(self, pattern, tunnel_config):
        super().__init__()
        self.tunnel = None
        self.aredis = None
        self.pattern = pattern
        self.tunnel_config = tunnel_config

    async def connect(self):
        self.tunnel = SSHTunnelForwarder(**self.tunnel_config)
        self.tunnel.start()

        address = self.tunnel.local_bind_address
        self.aredis = await aioredis.create_redis_pool(address, encoding="utf-8")
        logger.info(f"Redis connected: {self.aredis.address}")

    def redis_pattern(self):
        return self.pattern + "*" if self.pattern.endswith('.') else self.pattern

    async def send(self, message):
        if not self.aredis:
            raise RuntimeError("Redis not connected")

        if message.key.endswith("."):
            raise ValueError("trailing '.' in key")

        logger.info(f"Redis send: {message}:{message.value}")
        await self.aredis.publish(message.key, message.value)

    async def listen(self, pattern):
        if not self.aredis:
            raise RuntimeError("Redis not connected")

        try:
            chan, = await self.aredis.psubscribe(self.redis_pattern())
            while await chan.wait_message():
                k, v = await chan.get(encoding="utf-8")
                yield Message("redis", k.decode(), v)
        except Exception:
            raise

    async def status(self):
        if self.aredis:

            return {
                "status": "connected",
            #    "listeners": [str(p) for p, _ in self.listeners],
                "patterns": list(self.aredis.patterns.keys()),
                "timestamp": ts(),
            }
        else:
            return {"status": "disconnected"}

    async def close(self):
        self.aredis.close()
        await self.aredis.wait_closed()
        self.aredis = None

        self.tunnel.stop()
        logger.info(f"Redis connection closed")


class RedisMessageBridge:
    """ bridge a local MessageBus with an external Redis pubsub channel """

    def __init__(self, pattern, tunnel_config, bus):
        self.bus = bus
        self.aredis = None
        self.pattern = pattern
        self.tunnel_config = tunnel_config

    async def receiver(self):
        redis_pattern = self.pattern
        if redis_pattern.endswith('.'):
            redis_pattern += '*'

        try:
            chan, = await self.aredis.psubscribe(redis_pattern)
            while await chan.wait_message():
                k, v = await chan.get(encoding="utf-8")
                logger.info(f"bridge in {self.pattern}: message {k}: {v}")
                await self.bus.send(Message("redis", k.decode(), v))
        except asyncio.CancelledError:
            logger.info(f"bridge in {self.pattern}: cancelled")
        finally:
            await self.aredis.punsubscribe(redis_pattern)

    async def sender(self):
        """ route local messages to redis """

        try:
            async for message in self.bus.listen(self.pattern):
                if message.source != "redis":
                    logger.info(f"bridge out {self.pattern}: {message}")
                    await self.aredis.publish(message.key, message.value)
        except asyncio.CancelledError:
            logger.info(f"bridge out {self.pattern}: cancelled")

    async def start(self):
        """ open tunnel to redis server and start sender/receiver tasks """

        with SSHTunnelForwarder(**self.tunnel_config) as tunnel:
            address = tunnel.local_bind_address
            self.aredis = await aioredis.create_redis_pool(address, encoding="utf-8")
            logger.info(f"bridge connected: {self.aredis.address}")

            try:
                await asyncio.gather(
                    self.receiver(),
                    self.sender(),
                )
            except asyncio.CancelledError:
                logger.info(f"bridge start {self.pattern}: cancelled")
            except Exception as e:
                logger.info(f'bridge start {self.pattern}: exception {e} {type(e)}')

            self.aredis.close()
            await self.aredis.wait_closed()


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

    tunnel_config = {
        "ssh_address_or_host": ("robnee.com", 22),
        "remote_bind_address": ("127.0.0.1", 6379),
        "local_bind_address": ("127.0.0.1",),
        "ssh_username": "rnee",
        "ssh_pkey": os.path.expanduser(r"~/.ssh/id_rsa"),
    }

    ps = RedisMessageBus("cat.", tunnel_config)
    # ps = BasicMessageBus()
    await ps.connect()

    aws = (
        talk(ps, ("cat.dog", "cat.pig", "cow.emu")),
        listen(ps, "."),
        listen(ps, "cat."),
        listen(ps, "cat.pig"),
        monitor(),
        # RedisMessageBridge("cat.", tunnel_config, ps).start(),
    )
    tasks = [asyncio.create_task(c) for c in aws]
    await wait_gracefully(tasks, timeout=15)
    await ps.close()
    
    print("main: done")


if __name__ == "__main__":
    patch()
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    try:
        logger.addHandler(handler)
        asyncio.run(main(), debug=True)
    finally:
        logger.removeHandler(handler)
    print("all: done")
