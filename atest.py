import asyncio

import async_timeout

import os
import aioredis
from sshtunnel import SSHTunnelForwarder

STOPWORD = "STOP"


async def reader(channel: aioredis.client.PubSub):
    while True:
        try:
            async with async_timeout.timeout(1):
                message = await channel.get_message(ignore_subscribe_messages=True)
                if message is not None:
                    print(f"(Reader) Message Received: {message}")
                    if message["data"].decode() == STOPWORD:
                        print("(Reader) STOP")
                        break
                await asyncio.sleep(0.01)
        except asyncio.TimeoutError:
            pass


async def main():
    tunnel_config = {
        "ssh_address_or_host": ("robnee.com", 22),
        "remote_bind_address": ("127.0.0.1", 6379),
        "local_bind_address": ("127.0.0.1",),
        "ssh_username": "rnee",
        "ssh_pkey": os.path.expanduser(r"~/.ssh/id_rsa"),
    }

    with SSHTunnelForwarder(**tunnel_config) as tunnel:
        try:
            address = tunnel.local_bind_address
            url = "redis://{0}:{1}".format(*address)
            print("redis connecting", url)

            redis = await aioredis.from_url(url)
            print("redis connected")

            pubsub = redis.pubsub()
            await pubsub.psubscribe("channel:*")

            future = asyncio.create_task(reader(pubsub))

            await redis.publish("channel:1", "Hello")
            await redis.publish("channel:2", "World")
            await redis.publish("channel:1", STOPWORD)

            await future
        except Exception as e:
            print("ex: ", e)


if __name__ == "__main__":
    # asyncio.get_event_loop().run_until_complete(main())
    # asyncio.run will report an unhandled exception in 3.9 because pubsub will not fully clean up
    asyncio.run(main(), debug=True)