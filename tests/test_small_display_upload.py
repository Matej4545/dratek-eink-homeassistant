"""Exercise the real transfer loop for the two 296x128 controllers."""

import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from test_transfer_disconnect_safety import transfer


class SmallDisplayUploadTests(unittest.IsolatedAsyncioTestCase):
    async def run_upload(self, sdk_type, failed_block=None):
        writes = []
        payload = bytes(9472)
        char = SimpleNamespace(properties=["write", "write-without-response"])

        class Client:
            is_connected = True

            async def write_gatt_char(self, characteristic, data, response):
                if len(data) > 8:
                    index = int.from_bytes(data[:4], "little")
                    writes.append((index, response, data[4:]))
                    if index == failed_block:
                        raise TimeoutError("missing acknowledgement")

        @asynccontextmanager
        async def connected(*args):
            yield Client()

        sender = transfer.DratekTransfer(log=lambda message: None)
        sender._connected_client = connected
        sender._async_pack = AsyncMock(return_value=payload)
        sender._frame_for_display = lambda *args: (payload, False)
        sender._find_transfer_chars = lambda client: ("service", char, char)
        sender._start_notify = AsyncMock()
        sender._stop_notify = AsyncMock()
        sender._negotiate_mtu = AsyncMock()
        sender._request_block_size = AsyncMock(return_value=244)
        sender._wait_for_response = AsyncMock(return_value=b"\x02\x00")
        sender._wait_for_next_transfer_response = AsyncMock(
            side_effect=[b"\x05\x00\x00\x00\x00\x00", b"\x05\x08"]
        )
        await sender._send_once("FF:FF:92:81:66:82", sdk_type, None, software_version=129)
        return writes, payload

    async def test_both_small_controllers_acknowledge_all_40_blocks(self):
        for sdk_type in (46, 51):
            with self.subTest(sdk_type=sdk_type):
                writes, payload = await self.run_upload(sdk_type)
                self.assertEqual([item[0] for item in writes], list(range(40)))
                self.assertTrue(all(item[1] for item in writes))
                self.assertEqual(b"".join(item[2] for item in writes), payload)

    async def test_missing_middle_ack_does_not_report_success(self):
        with self.assertRaises(TimeoutError):
            await self.run_upload(46, failed_block=10)

    async def test_final_ack_timeout_can_finish_with_vendor_confirmation(self):
        writes, _ = await self.run_upload(46, failed_block=39)
        self.assertEqual(len(writes), 40)


if __name__ == "__main__":
    unittest.main()
