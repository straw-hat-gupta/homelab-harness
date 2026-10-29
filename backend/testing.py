"""Shared helpers for the test suite."""
import asyncio

from asgiref.sync import sync_to_async
from django.db import connections


def run_async(coro):
    """Run a coroutine to completion from synchronous test code.

    Code under test reaches the ORM through ``sync_to_async``, which runs on
    asgiref's thread-sensitive executor thread when there is no outer sync
    context. That thread opens its own database connection; closing it here
    keeps test-database teardown from failing with "being accessed by other
    users".
    """

    async def _wrapper():
        try:
            return await coro
        finally:
            await sync_to_async(connections.close_all)()

    return asyncio.run(_wrapper())
