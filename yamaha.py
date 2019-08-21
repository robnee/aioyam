#! /usr/bin/python3

'''
python code to control Yamaha AV receiver via YCNA protocol.  Of note is that
put command will not respond if the value being put is the same as the
current setting.  put API handles this by using a get request if no response
is received.  This can be skipped by using a timeout of 0.  parse_response will
turn a response string into a dict for easy access.  request returns None on
connection problem, '@ERROR' on error and the response string otherwise.
'''

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
        print(self.decode_response())
        self.on_con_lost.set_result(True)

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
    ''' Yamaha YNCA controller '''
    def __init__(self, hostname=None, port=50000):
        self.port = port
        self.hostname = hostname
        self.request_id = 0

    def request(self, hostname, timeout, name, value):
        """ send a request and depending on the timeout value wait for and
        return a response"""
        self.request_id += 1
        msg = name + "=" + value + "\r\n"

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(max(timeout, 0.1))
            s.connect((hostname, self.port))
        except (InterruptedError):
            print("cant connect to", hostname, "on", self.port)
            return None

        try:
            s.sendall(bytes(msg, 'utf-8'))
            s.settimeout(timeout)
            response = ''
            while True:
                data = s.recv(1024)
                if not data:
                    break
                response = response + data.decode()
        except socket.timeout:
            pass
        except socket.error:
            return None
        finally:
            s.close()
            s = None

        response = response.rstrip('\n\r')

        if False:
            print('request {}: {}={}'.format(self.request_id, name, value))
            print('response {}: {}'.format(self.request_id, repr(response)))

        # decode data and check if response indicates error
        if response == "@UNDEFINED" or response == '@RESTRICTED':
            return '@ERROR'

        return response

    def parse_response(self, response):
        """ Build a dict of the response values """
        results = {}

        exp = re.compile(r"(.*)=(.*)\s*", re.IGNORECASE)
        for line in response.split("\r\n"):
            if line:
                m = exp.match(line)
                results[m.group(1)] = m.group(2)

        return results

    def get(self, name, timeout=0.05):
        """ send request to get value """
        return self.request(self.hostname, timeout, name, '?')

    def put(self, name, value, timeout=0.05):
        """ send request.  use timeout of 0 to skip waiting for response """
        response = self.request(self.hostname, timeout, name, value)

        # Protocol won't answer if we try to PUT value that is already
        # set to the same value.  if we indicated a timeout and no
        # respponse was received then get and return the current value
        if timeout > 0 and response == '':
            return self.get(name, timeout * 2.0)
        else:
            return response


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


async def main():
    # Get a reference to the event loop as we plan to use
    # low-level APIs.
    loop = asyncio.get_running_loop()

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


if __name__ == '__main__':
    asyncio.run(main())
