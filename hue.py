#! /usr/bin/env python3

"""
Proof of concept for simple pubsub system with Redis bridge.  this will be the messaging
backbone of the next remote control system
"""

import os
import time
import logging
import asyncio
import aioredis
from collections import namedtuple
from sshtunnel import SSHTunnelForwarder
from aiotools import patch, wait_gracefully
from phue import Bridge

Message = namedtuple("Message", "source, target, key, value")

logger = logging.getLogger(__name__)


def ts():
    return time.time()


class MessageBus:
    """ MessageBus interface """

    async def send(self, message):
        pass

    async def listen(self, pattern):
        pass

    async def close(self):
        pass


# todo: should this be initialized with a mask to restrict the namespace?
# todo: using patterns makes many of the status metrics unavailable.
# todo: Should there just be a single channel?
class RedisMessageBus(MessageBus):
    """ A MessageBus implemented as a Redis pubsub channel """

    def __init__(self, pattern):
        super().__init__()
        self.tunnel = None
        self.aredis = None
        self.pattern = pattern

    async def connect(self, tunnel_config):
        def create_tunnel():
            self.tunnel = SSHTunnelForwarder(**tunnel_config)
            self.tunnel.start()

        await asyncio.get_event_loop().run_in_executor(None, create_tunnel)

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

    async def listen(self, pattern='*'):
        """ todo: how to map from source, target, k, v to redis """

        if not self.aredis:
            raise RuntimeError("Redis not connected")

        try:
            chan, = await self.aredis.psubscribe(self.redis_pattern())
            while await chan.wait_message():
                k, v = await chan.get(encoding="utf-8")
                # todo: add target arg
                yield Message("redis", k.decode(), v)
        except Exception:
            raise

    async def status(self):
        if self.aredis:

            return {
                "status": "connected",
                "patterns": list(self.aredis.patterns.keys()),
                "timestamp": ts(),
            }
        else:
            return {"status": "disconnected"}

    async def close(self):
        self.aredis.close()
        await self.aredis.wait_closed()
        self.aredis = None

        # this is slow so run in a thread pool
        await asyncio.get_event_loop().run_in_executor(None, self.tunnel.stop)
        self.tunnel = None
        logger.info(f"Redis connection closed")


class HueComponent:
    """ bridge Hue bridge onto MessageBus """

    def __init__(self, bridge_hostname, bus):
        self.bus = bus
        self.bridge = Bridge(bridge_hostname)

        # start up the listener
        self.listen_task = asyncio.create_task(self.listen())

    async def listen(self):
        """ listen for commands and relay them to the component """
        try:
            async for message in self.bus.listen():
                if message.source.startswith(""):
                    print(f"Bridge:", message)
        except asyncio.CancelledError:
            pass

    async def close(self):
        """ Shut down the listener """
        self.listen_task.cancel()
        self.listen_task = None

        logger.info(f"Bridge: closed")


async def main():
    """ main entry point """

    async def talk(bus, keys):
        """ generate some test messages """

        for v in range(5):
            for k in keys:
                await asyncio.sleep(0.35)
                await bus.send(Message("local", k, v))

    async def listen(bus, pattern):
        """ listen on the bus """

        await asyncio.sleep(1.5)
        try:
            async for message in bus.listen(pattern):
                print(f"listen({pattern}):", message)
        except asyncio.CancelledError:
            pass

    async def monitor():
        """ echo bus status every 2 sec """

        count = 0
        try:
            while True:
                await asyncio.sleep(1)
                count += 1
                print(f"monitor status: 0:{count:02}", await ps.status())
        except asyncio.CancelledError:
            pass

    tunnel_config = {
        "ssh_address_or_host": ("robnee.com", 22),
        "remote_bind_address": ("127.0.0.1", 6379),
        "local_bind_address": ("127.0.0.1",),
        "ssh_username": "rnee",
        "ssh_pkey": os.path.expanduser(r"~/.ssh/id_rsa"),
    }

    ps = RedisMessageBus("cat.")
    await ps.connect(tunnel_config)

    hue = HueComponent('Philips-hue.home', ps)

    tasks = [asyncio.create_task(c) for c in (
        talk(ps, ("cat.dog", "cat.pig", "cow.emu")),
        listen(ps, "."),
        listen(ps, "cat."),
        listen(ps, "cat.pig"),
        monitor(),
    )]

    await wait_gracefully(tasks, timeout=12)
    await hue.close()
    await ps.close()
    print("main: done")


if __name__ == "__main__":
    print("all: start")
    patch()
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    try:
        logger.addHandler(handler)
        asyncio.run(main(), debug=True)
    finally:
        logger.removeHandler(handler)
    print("all: done")
