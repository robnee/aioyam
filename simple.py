#! /usr/bin/env python3

"""
simple demo with a yamaha target on a simple message bus
"""

import os
import re
import time
import logging
import asyncio
import aioredis
from sshtunnel import SSHTunnelForwarder

from aiotools import patch
from yamaha import Yamaha
from bus import MessageBus


logger = logging.getLogger()


def ts():
    return time.time()


class RegexPattern:
    """ regex patterns """

    def __init__(self, pattern):
        self.regex = re.compile(pattern)

    def match(self, subject):
        return self.regex.fullmatch(subject)


class DotPattern:
    """ dot-separated path-style patterns """

    def __init__(self, pattern):
        self.pattern = pattern.upper()

    def match(self, subject):
        if self.pattern == subject.upper() or self.pattern in ("", "."):
            return True

        prefix = self.pattern + "" if self.pattern[-1] == "." else "."
        return subject.upper().startswith(prefix)


class BasicMessageBus(MessageBus):
    """ Basic MessageBus implementation """

    def __init__(self):
        super().__init__()
        self.conn = None
        self.listeners = set()

    async def connect(self, address=None):
        self.conn = self
        logger.info(f"connected ({address})")

    async def send(self, k, v):
        if not self.conn:
            raise RuntimeError("not connected")

        if k.endswith("."):
            raise ValueError("trailing '.' in key")
        self.set_channel(k, v)
        for pattern, q in self.listeners:
            if pattern.match(k):
                await q.put(MessageBus.new_message(k, v))

    async def listen(self, pattern):
        if not self.conn:
            raise RuntimeError("not connected")

        try:
            p = DotPattern(pattern)
            q = asyncio.Queue()

            self.listeners.add((p, q))

            # yield current values
            for k, v in self.get_channels():
                if p.match(k):
                    yield self.new_message(k, v)

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
                "listeners": len(self.listeners),
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


class YamahaAdapter:
    """ interface Yamaha target to mmessage bus """
    def __init__(self, bus):
        self.bus = bus
        self.yam = Yamaha()
        
    async def listener(self, key):
        async for msg in self.bus.listen(key):
            print(f"listen({key}):", msg)
            if msg:
                k, v = msg
                self.yam.put(k, v)
                print('adaptor: {k}, {v}')

        print(f"listen {key}: done")
     

async def main():
    """ main entry point """

    ps = BasicMessageBus()
    await ps.connect()

    async def talk(keys, sleep_time=0.35):
        print(f"talk {len(keys)} {sleep_time}: start")

        try:
            for n in range(5):
                for k in keys:
                    await asyncio.sleep(sleep_time)
                    await ps.send(k, n)
        except asyncio.CancelledError:
            print("talk cancelled:")

        await ps.close()
        print("talk: done")

    async def listen(k):
        await asyncio.sleep(1.5)
        async for x in ps.listen(k):
            print(f"listen({k}): {(ts() - x.ts) * 1000000:.0f}us: {x}")
        print(f"listen {k}: done")

    async def mon():
        try:
            for _ in range(15):
                await asyncio.sleep(1)
                s = await ps.status()
                print(f"mon status {_}:", s)
        except asyncio.CancelledError:
            print("mon cancelled:")

        print("mon: done")

        return True

    async def bridge_orig(pattern, bus):
        tunnel_config = {
            "ssh_address_or_host": ("robnee.com", 22),
            "remote_bind_address": ("127.0.0.1", 6379),
            "local_bind_address": ("127.0.0.1",),
            "ssh_username": "rnee",
            "ssh_pkey": os.path.expanduser(r"~/.ssh/id_rsa"),
        }

        with SSHTunnelForwarder(**tunnel_config) as tunnel:
            address = tunnel.local_bind_address
            print("redis connecting", address)
            aredis = await aioredis.create_redis(address, encoding="utf-8")

            print("redis connected", aredis.address)

            try:
                chan, = await aredis.psubscribe(pattern)
                while await chan.wait_message():
                    k, v = await chan.get(encoding="utf-8")
                    await bus.send(k.decode(), v)

                print("watch: done")
            except asyncio.CancelledError:
                print("watch cancelled:", pattern)
            except Exception as e:
                print("bridge exception:", type(e), e)
            finally:
                print("watch finally")

                aredis.close()
                await aredis.wait_closed()

        print("watch done:", pattern)

    async def reader(channel: aioredis.client.PubSub):
        while True:
            try:
                message = await channel.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is not None:
                    print(f"(Reader) Message Received: {message}")
                    if message["data"].decode() == "STOPWORD":
                        print("(Reader) STOP")
                        break
                await asyncio.sleep(0.01)
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                print("reader cancelled:")
                break

    async def bridge(pattern, bus):
        tunnel_config = {
            "ssh_address_or_host": ("robnee.com", 22),
            "remote_bind_address": ("127.0.0.1", 6379),
            "local_bind_address": ("127.0.0.1",),
            "ssh_username": "rnee",
            "ssh_pkey": os.path.expanduser(r"~/.ssh/id_rsa"),
        }

        with SSHTunnelForwarder(**tunnel_config) as tunnel:
            address = tunnel.local_bind_address
            url = "redis://{0}:{1}".format(*address)
            print("redis connecting", url)

            redis = aioredis.from_url(url)
            print("redis connected")

            try:
                pubsub = redis.pubsub()

                # Subscribing won't fully clean up so expect asyncio errors on shutdown
                response = await pubsub.psubscribe(pattern)
                print("subscribe:", response)

                await reader(pubsub)

                print("watch: reader exited")
            except asyncio.CancelledError:
                print("watch cancelled:", pattern)
            except Exception as e:
                print("bridge exception:", type(e), e)
            finally:
                print("watch finally")

            # unsubscribe from all
            response = await pubsub.punsubscribe()
            print("unsubscribe:", response)

            del pubsub

        print("watch done:", pattern)

    coros = (
        talk(("cat.dog", "cat.pig", "cow.emu")),
        listen("."),
        listen("cat."),
        listen("cat.pig"),
        bridge("cat.*", ps),
        mon(),
    )
    done, pending = await asyncio.wait(tuple(asyncio.create_task(c) for c in coros), timeout=10)

    print("run done:", len(done), "pending:", len(pending))
    for t in pending:
        print(f"cancelling {t.get_name()}:")
        t.cancel()
        # result = await t
        # print('cancel:', result)

    for t in done:
        if t.exception():
            print(f"result {t.get_name()}: exception: {t.exception()}")
        else:
            print(f"result {t.get_name()}: {t.result()}")

    print("main: done")


if __name__ == "__main__":
    patch()
    asyncio.run(main(), debug=True)
    print("all: done")
