#!/usr/bin/env python3

import io
import unittest
from http.client import IncompleteRead
from unittest.mock import patch

from scripts.verify_cbb_api_foundation import fetch_json


class BrokenResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, *_args, **_kwargs):
        raise IncompleteRead(b"[]", 10)


class GoodResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False


class CbbApiFoundationTests(unittest.TestCase):
    @patch("scripts.verify_cbb_api_foundation.time.sleep")
    @patch("scripts.verify_cbb_api_foundation.urlopen")
    def test_retries_incomplete_provider_response(self, mocked_urlopen, mocked_sleep):
        mocked_urlopen.side_effect = [BrokenResponse(), GoodResponse(b'[{"gameId": 1}]')]

        payload = fetch_json("/games", {"season": 2027}, "test-key")

        self.assertEqual(payload, [{"gameId": 1}])
        self.assertEqual(mocked_urlopen.call_count, 2)
        mocked_sleep.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
