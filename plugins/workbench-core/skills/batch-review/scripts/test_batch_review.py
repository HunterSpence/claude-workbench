import os, sys, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import batch_review as br


class BatchReviewTest(unittest.TestCase):
    def test_build_requests(self):
        reqs = br.build_requests(["a", "b"], "m", 100, effort="high", system="sys")
        self.assertEqual([r["custom_id"] for r in reqs], ["req-0", "req-1"])
        self.assertEqual(reqs[1]["params"], {"model": "m", "max_tokens": 100, "messages": [{"role": "user", "content": "b"}],
                                             "output_config": {"effort": "high"}, "system": "sys"})
        self.assertNotIn("output_config", br.build_requests(["a"], "m", 1)[0]["params"])

    def test_missing_key_stops_before_any_call(self):
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(SystemExit) as cm:
            br.main(["hello"])
        self.assertIn("Console API key", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
