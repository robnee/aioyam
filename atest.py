import asyncio

import async_timeout

import os
import aioredis
from sshtunnel import SSHTunnelForwarder

STOPWORD = "STOP"


async def reader(channel: aioredis.client.PubSub):
    while True:
        try:
            print("reader: start")
            async for message in channel.listen():
                print(message)
                if message['data'].decode() == STOPWORD:
                    print('break')
                    return
        except asyncio.CancelledError:
            print("reader cancelled:")
        except Exception as e:
            print("reader exception:", type(e), e)


async def main():
    tunnel_config = {
        "ssh_address_or_host": ("robnee.com", 22),
        "remote_bind_address": ("127.0.0.1", 6379),
        "local_bind_address": ("127.0.0.1",),
        "ssh_username": "rnee",
        "ssh_pkey": os.path.expanduser(r"~/.ssh/id_rsa"),
    }

    print(tunnel_config)
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
            await asyncio.sleep(2)
            await redis.publish("channel:2", "World")
            await asyncio.sleep(2)
            await redis.publish("channel:1", STOPWORD)

            x = await future
            print(x, future)

            await redis.close()
        except Exception as e:
            print("ex: ", e)


if __name__ == "__main__":
    # asyncio.get_event_loop().run_until_complete(main())
    # asyncio.run will report an unhandled exception in 3.9 because pubsub will not fully clean up
    try:
        asyncio.run(main())
    except RuntimeError as e:
        print(e)