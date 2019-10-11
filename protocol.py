import sys
import asyncio
import yamaha


class YNCAProtocol(asyncio.Protocol):
    def __init__(self, name, value, on_con_lost, loop=None):
        self.message = name + "=" + value + "\r\n"
        self.loop = loop
        self.data = ""
        self.on_con_lost = on_con_lost

    def connection_made(self, transport):
        transport.write(self.message.encode())
        print('Data sent: {!r}'.format(self.message))

    def data_received(self, data):
        print('Data received: {!r}'.format(data.decode()))
        self.data += data.decode()

    def connection_lost(self, exc):
        print('The server closed the connection')
        if not self.on_con_lost.cancelled():
            response = yamaha.decode_response(self.data)
            print("future done:", self.on_con_lost.done(), "cancelled:", self.on_con_lost.cancelled())
            self.on_con_lost.set_result(response)


class Yamaha:
    """ Yamaha YNCA controller """
    def __init__(self, hostname=None, port=50000):
        self.port = port
        self.hostname = hostname
        self.request_id = 0

    async def request(self, hostname, name, value, timeout=None):
        """ send a request and depending on the timeout value wait for and
        return a response"""
        self.request_id += 1

        loop = asyncio.get_running_loop()

        done = loop.create_future()
        try:
            transport, protocol = await loop.create_connection(
                lambda: YNCAProtocol(name, value, done),
                hostname, 50000)
        except Exception as e:
            print("create conn:", e)
            
            return

        print("connect:")
        # Wait until the protocol signals that the connection
        # is lost and close the transport.
        
        try:
            print("awaiting done")
            await done
            print("done:", done.result())
        except asyncio.CancelledError:
            print("request cancelled")
        finally:
            print('finally close:')
            transport.close()

        print("done result:", done.result())
        return done.result()

    async def get(self, name, timeout=0.05):
        """ send request to get value """
        try:
            x = await asyncio.wait_for(self.request(self.hostname, name, '?'),
                                       timeout=timeout)
            print("request:", x)
            return x
        except asyncio.TimeoutError as e:
            print('timeout:', e)
            return None

    async def put(self, name, value, timeout=0.05):
        """ send request.  use timeout of 0 to skip waiting for response """
        try:
            x = await asyncio.wait_for(self.request(self.hostname, name, value),
                                       timeout=timeout)
            print("request:", x)
            return x
        except asyncio.TimeoutError as e:
            print('timeout:', e)
            # Protocol won't answer if we try to PUT value to a name that
            # is already set to the same value.  if we indicated a timeout and
            # no response was received then get and return the current value
            return self.get(name, timeout * 2.0)


async def main():
    # Get a reference to the event loop as we plan to use
    # low-level APIs.
    loop = asyncio.get_event_loop()

    on_con_lost = loop.create_future()

    name, value = "@MAIN:PWR", "On"

    transport, protocol = await loop.create_connection(
        lambda: YNCAProtocol(name, value, on_con_lost, loop),
        'CL-6EA47', 50000)

    # Wait until the protocol signals that the connection
    # is lost and close the transport.
    try:
        await on_con_lost
    finally:
        transport.close()


def run(future):
    loop = asyncio.get_event_loop()

    result = loop.run_until_complete(future)
    print("result:", result)


def patch():
    """ monkey patch some Python 3.7 stuff into earlier versions """
    version = sys.version_info.major * 10 + sys.version_info.minor
    if version < 37:
        asyncio.get_running_loop = asyncio.get_event_loop
        asyncio.run = run
   

if __name__ == '__main__':
    patch()
    # asyncio.run(main2())
    run(main())
