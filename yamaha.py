#! /usr/bin/python3

"""
python code to control Yamaha AV receiver via YNCA protocol.  Of note is that
put command will not respond if the value being put is the same as the
current setting.  put API handles this by using a get request if no response
is received.  This can be skipped by using a timeout of 0.  parse_response will
turn a response string into a dict for easy access.  request returns None on
connection problem, '@ERROR' on error and the response string otherwise.

samples:
    print("pwr", yam.put("@MAIN:PWR", "On"))
    print("pwr", yam.put("@MAIN:PWR", "Standby"))
    print("get vol", yam.get("@MAIN:VOL"))
    print("vol bad", yam.put("@MAIN:VOL", 'Up 2 Db'))
    print("vol good", yam.put("@MAIN:VOL", 'Down 2 dB', timeout))
"""

import re
import sys
import asyncio
import logging
import warnings


"""
Protocols are fine but they are actually synchronous.  it might be tricky to incorporate the becessary back-end calls later.
Protocols, at least this example, use a somewhat awkward callback to signal done.
todo: write a dummy server task to mock the endpoint for testing
"""


def decode_response(data):
    response = data.rstrip('\n\r')

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


async def ynca_request(address, message, timeout=1):
    if type(address) == str:
        reader, writer = await asyncio.open_connection(address, 50000)
    else:
        reader, writer = await asyncio.open_connection(*address)

    print(f'Send: {message!r}')
    writer.write(message.encode())

    response = []
    while True:
        try:
            data = await asyncio.wait_for(reader.readuntil(b'\r\n'), timeout=timeout)
            print(f'Received: {len(data)}: {data.decode()!r}')
            response.append(data.decode())
        except asyncio.IncompleteReadError as e:
            print('incomplete:', e)
            break
        except asyncio.TimeoutError as e:
            print('timeout:', e)
            break

    writer.close()

    return decode_response(''.join(response))


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

        try:
            message = name + "=" + value + "\r\n"
            response = await ynca_request((hostname, 50000), message)
        except Exception as e:
            print("ynca exception:", type(e), e)
            return
  
        return response

    async def get(self, name, timeout=0.05):
        """ send request to get value """
        return await self.request(self.hostname, name, '?', timeout=timeout)

    async def put(self, name, value, timeout=0.05):
        """ send request.  use timeout of 0 to skip waiting for response """
        x = await self.request(self.hostname, name, value, timeout=timeout)
        if not x and timeout:
            # Protocol won't answer if we try to PUT value to a name that
            # is already set to the same value.  if we indicated a timeout and
            # no response was received then get and return the current value
            return self.get(name, timeout * 2.0)


async def ynca_server():
    """ Mock YNCA host """

    async def handle_request(reader, writer):
        data = await reader.read(100)
        message = data.decode()
        addr = writer.get_extra_info('peername')
    
        print(f"server received {message!r} from {addr!r}")

        response = b'@MAIN:PWR=Standby\r\n@MAIN:AVAIL=Not Ready\r\n'
        print(f"server send: {response!r}")
        writer.write(response)
        await writer.drain()

        await asyncio.sleep(5)

        print("close the connection")
        writer.close()

    server = await asyncio.start_server(handle_request, '127.0.0.1', 50000)

    addr = server.sockets[0].getsockname()
    print(f'serving on {addr}')

    await asyncio.sleep(30)
    
    server.close()
    print('done serving')


async def main():
    async def test():
        await asyncio.sleep(0.25)

        hostname = 'CL-6EA47'
        hostname = '127.0.0.1'
        yam = Yamaha(hostname)
    
        # x = await yam.put("@MAIN:VOL", "Up 2 dB", 0.1)
        x = await yam.put("@MAIN:PWR", "On", 5)
        # x = await yam.get("@MAIN:VOL", 60)
        
        print("response", x)
    
    await asyncio.gather(test(), ynca_server())


def patch():
    """ monkey patch some Python 3.7 stuff into earlier versions """

    def run(task, debug=False):
        try:
            loop = asyncio.get_event_loop()
        except:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        if debug:
            loop.set_debug(True)
            logging.getLogger('asyncio').setLevel(logging.DEBUG)
            warnings.filterwarnings('always')
        else:
            loop.set_debug(False)
            logging.getLogger('asyncio').setLevel(logging.WARNING)
            warnings.filterwarnings('default')
            
        return loop.run_until_complete(task)
        
    version = sys.version_info.major * 10 + sys.version_info.minor
    if version < 37:
        asyncio.get_running_loop = asyncio.get_event_loop
        asyncio.create_task = asyncio.ensure_future
        asyncio.run = run


if __name__ == '__main__':
    patch()
    asyncio.run(main())
