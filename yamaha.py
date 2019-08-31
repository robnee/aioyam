#! /usr/bin/python3

"""
python code to control Yamaha AV receiver via YNCA protocol.  Of note is that
put command will not respond if the value being put is the same as the
current setting.  put API handles this by using a get request if no response
is received.  This can be skipped by using a timeout of 0.  parse_response will
turn a response string into a dict for easy access.  request returns None on
connection problem, '@ERROR' on error and the response string otherwise.
"""

import re
import asyncio


class YNCAProtocol(asyncio.Protocol):
    def __init__(self, name, value, on_con_lost, loop):
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
        response = self.decode_response()
        self.on_con_lost.set_result(response)

    def decode_response(self):
        response = self.data.rstrip('\n\r')

        # decode data and check if response indicates error
        if response == "@UNDEFINED" or response == '@RESTRICTED':
            return '@ERROR'

        if '\r\n' in response:
            results = {}

            exp = re.compile(r"(.*)=(.*)\s*", re.IGNORECASE)
            for line in response.split("\r\n"):
                if line:
                    m = exp.match(line)
                    results[m.group(1)] = m.group(2)
            response = results

        return response


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

        transport, protocol = await loop.create_connection(
            lambda: YNCAProtocol(name, value, done, loop),
            hostname, 50000)

        # Wait until the protocol signals that the connection
        # is lost and close the transport.
        try:
            await done
        finally:
            transport.close()

        return done.result()

    async def get(self, name, timeout=0.05):
        """ send request to get value """
        return await self.request(self.hostname, name, '?')

    async def put(self, name, value, timeout=0.05):
        """ send request.  use timeout of 0 to skip waiting for response """
        try:
            x = await self.request(self.hostname, name, value)
            print("request:", x)
            return x
        except TimeoutError:
            # Protocol won't answer if we try to PUT value to a name that
            # is already set to the same value.  if we indicated a timeout and
            # no response was received then get and return the current value
            return self.get(name, timeout * 2.0)


def test():
    import time

    hostname = 'Yamaha'
    yam = Yamaha(hostname)

    # adjust timeout setting (0.01 - 0.20) to test response speed of receiver
    timeout = 0

    print('receiver at', yam.hostname)

    start = time.time()

    print("pwr", yam.put("@MAIN:PWR", "On"))
    print("pwr", yam.put("@MAIN:PWR", "On"))

    # print("input hdmi1", yam.put("@MAIN:INP", 'AV1'))
    print("get vol", yam.get("@MAIN:VOL"))
    print("vol bad", yam.put("@MAIN:VOL", 'Up 2 Db'))

    for _ in range(10):
        time.sleep(0.1)
        print()
        print("vol good", repr(yam.put("@MAIN:VOL", 'Up 2 dB', timeout)))
        time.sleep(0.1)
        print("vol good", repr(yam.put("@MAIN:VOL", 'Down 2 dB', timeout)))
    # print("pwr", yam.put("@MAIN:PWR", "Standby"))

    print('total: {:0.3f}'.format(time.time() - start))


async def main2():

    hostname = 'CL-6EA47'
    yam = Yamaha(hostname)

    x = await yam.put("@MAIN:PWR", "Standby", 0.1)
    print("main2", x)


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


def run(futures, timeout=None):
    loop = asyncio.get_event_loop()

    if type(futures) is not list:
        futures = {futures}

    # done, pending = loop.run_until_complete(asyncio.wait(futures), timeout=timeout)
    done, pending = loop.run_until_complete(asyncio.wait(futures, timeout=timeout))

    for task in pending:
        task.cancel()

   
if __name__ == '__main__':
    # asyncio.run(main2())
    run(main2(), 1)
