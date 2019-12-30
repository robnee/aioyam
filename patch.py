""" monkey patch some Python 3.7/3.8 stuff into earlier versions """

import re
import sys
import asyncio
import warnings
import logging


def asyncio_run(task, debug=False):
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


def task_get_name(self):
    """ asyncio.tasks.Task.get_name """

    match = re.search(r"coro=<(\S+)", repr(self))
    return match.group(1).replace('.<locals>', '')


def patch():
    """ monkey patch some Python 3.7/3.8 stuff into earlier versions """

    version = sys.version_info.major * 10 + sys.version_info.minor

    if version < 37:
        asyncio.get_running_loop = asyncio.get_event_loop
        asyncio.create_task = asyncio.ensure_future
        asyncio.current_task = asyncio.Task.current_task
        asyncio.all_tasks = asyncio.Task.all_tasks
        asyncio.run = asyncio_run
        asyncio.tasks.Task.get_name = task_get_name
