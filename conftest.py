"""Root pytest configuration: applies to every test path, the integrations' suites included."""
import asyncio
import sys

if sys.platform == "win32":
    # grpc.aio on a Proactor loop has its one poller thread hand events to loops with call_soon_threadsafe; an event
    # arriving after a test closed its loop raises "Event loop is closed" there, the thread dies, and every later
    # grpc.aio call in the session hangs. Selector loops let grpc watch its wakeup socket instead, so it never does.
    # shortcut: the policy API is deprecated from Python 3.14; pass a loop_factory per runner when CI moves to 3.14.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
