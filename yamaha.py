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
Protocols are fine but they are actually synchronous.  it might be tricky to incorporate the becessary back-end
calls later.  Protocols, at least this example, use a somewhat awkward callback to signal done.
todo: write a dummy server task to mock the endpoint for testing
"""


def decode_response(data):
    """ Convert response to a dict """

    response = data.rstrip('\r\n')
    logging.info(f"raw response {response!r}")

    # decode data and check if response indicates error
    results = {}
    if response in ("@UNDEFINED", '@RESTRICTED', '@ERROR'):
        results = {'response': '@ERROR'}
    else:
        exp = re.compile(r"(.*)=(.*)\s*", re.IGNORECASE)
        for line in response.split("\r\n"):
            if line:
                m = exp.match(line)
                results[m.group(1)] = m.group(2)
        results['response'] = '@OK'

    return results


async def ynca_request(address, message, timeout=1):
    if type(address) == str:
        reader, writer = await asyncio.open_connection(address, 50000)
    else:
        reader, writer = await asyncio.open_connection(*address)

    # ensure the message is properly terminated
    if not message.endswith('\r\n'):
        message += '\r\n'

    writer.write(message.encode())

    response = []
    while True:
        try:
            data = await asyncio.wait_for(reader.readuntil(b'\r\n'), timeout=timeout)
            response.append(data.decode())
        except asyncio.IncompleteReadError as e:
            logging.info(f"ynca_request incomplete read ({e}): {address!r} {message!r}")
            break
        except asyncio.TimeoutError:
            if not response:
                logging.info(f"ynca_request timeout({timeout}): {address!r} {message!r}")
            break

    writer.close()

    return decode_response(''.join(response))


class Yamaha:
    """ Yamaha YNCA controller """

    def __init__(self, hostname=None, port=50000):
        self.port = port
        self.hostname = hostname
        self.request_id = 0
        self.timeout = 0.05
        
    def set_timeout(self, timeout):
        self.timeout = timeout

    async def request(self, hostname, name, value, timeout=None):
        """ send a request and depending on the timeout value wait for and
        return a response """

        self.request_id += 1

        try:
            message = name + "=" + value + "\r\n"
            response = await ynca_request((hostname, 50000), message, 
                                          timeout or self.timeout)
        except Exception as e:
            print("ynca exception:", type(e), e)
            return
        else:
            return response

    async def get(self, name, timeout=None):
        """ send request to get value of name """

        return await self.request(self.hostname, name, '?',
                                  timeout=timeout or self.timeout)

    async def put(self, name, value, timeout=None):
        """ send request to set name to value.  A timeout of 0 skips wait for response """

        timeout = timeout or self.timeout
        
        x = await self.request(self.hostname, name, value, timeout=timeout)
        if not x and timeout:
            # Protocol won't answer if we try to PUT value to a name that
            # is already set to the same value.  if we indicated a timeout and
            # no response was received then get and return the current value
            return await self.get(name, timeout * 2.0)

        return x


class YNCAServer:
    """ Mock YNCA host """

    def __init__(self):
        self.server = None

    # todo: implement multiple requests
    @staticmethod
    async def handle_request(reader, writer):
        try:
            data = await reader.read(100)
            message = data.decode()
            addr = writer.get_extra_info('peername')

            logging.info(f"handle_request: received {message!r} from {addr!r}")
    
            response = b'@MAIN:PWR=Standby\r\n@MAIN:AVAIL=Not Ready\r\n'
            writer.write(response)
            await writer.drain()

            await asyncio.sleep(5)

            logging.info("handle: close request connection")
            writer.close()

            logging.info("handle: request done")
        except OSError as e:
            logging.info('server: error start', e)
            return

    async def start(self):
        try:
            self.server = await asyncio.start_server(self.handle_request, '127.0.0.1', 50000)
            addr = self.server.sockets[0].getsockname()
            print(f'server: on {addr}')
            print('server:', self.server)
        except OSError as e:
            print('server: error start', e)
        except asyncio.CancelledError as e:
            print('server: cancel exception:', type(e))
            self.server.close()
            await self.server.wait_closed()

    def close(self):
        if self.server:
            self.server.close()

       
async def main():
    async def test(hostname):
        await asyncio.sleep(1)

        yam = Yamaha(hostname)
    
        # x = await yam.put("@MAIN:VOL", "Up 2 dB")
        x = await yam.put("@MAIN:PWR", "Standby")
        # x = await yam.get("@MAIN:VOL")
        
        print("test: response:", x)
    
    # todo: can we start ynca_server as a task?
    # todo: how can we cleanly cancel it?  Should server_task be owned by the class?
    # await asyncio.gather(test(), ynca_server())
    ynca = YNCAServer()
    await ynca.start()

    await test('127.0.0.1')
    # await test('CL-6EA47')

    # Let it run for a few seconds
    t = 4
    print(f'main: sleep {t}')
    await asyncio.sleep(t)
    
    print(f'main: stop server')
    ynca.close()

    print('main: done')


def patch():
    """ monkey patch some Python 3.7 stuff into earlier versions """

    def run(task, debug=False):
        try:
            loop = asyncio.get_event_loop()
        except Exception:
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
            
        response = loop.run_until_complete(task)
        
        loop.run_until_complete(loop.shutdown_asyncgens())
        
        return response

    version = sys.version_info.major * 10 + sys.version_info.minor
    if version < 37:
        asyncio.get_running_loop = asyncio.get_event_loop
        asyncio.create_task = asyncio.ensure_future
        asyncio.current_task = asyncio.Task.current_task
        asyncio.all_tasks = asyncio.Task.all_tasks
        asyncio.run = run


if __name__ == '__main__':
    patch()

    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

    asyncio.run(main(), debug=False)
