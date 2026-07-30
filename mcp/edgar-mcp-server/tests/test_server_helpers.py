import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from edgar_mcp_server.server import (
    _clean_markdown,
    _output_dir,
    _safe_filename,
    _select_forms,
    _normalize_alias,
)


class ServerHelperTests(unittest.TestCase):
    def test_select_forms(self):
        self.assertEqual(_select_forms("both"), ["10-K", "10-Q"])
        self.assertEqual(_select_forms("10-K"), ["10-K"])
        self.assertEqual(_select_forms("10-Q"), ["10-Q"])

    def test_normalize_alias(self):
        self.assertEqual(_normalize_alias(" 苹果 公司 "), "苹果公司")
        self.assertEqual(_normalize_alias("英伟达（NVIDIA）"), "英伟达nvidia")

    def test_safe_filename(self):
        self.assertEqual(
            _safe_filename("AAPL", "2023", "10-K", "000/032:0193"),
            "AAPL_2023_10-K_000_032_0193",
        )

    def test_clean_markdown_compresses_noise(self):
        raw = (
            "Title\x00\r\n\r\n\r\n| a  | b |\n| 1 |  2 |\n\n{3}-----\n"
            "<div align='center'>text     with      spaces&nbsp;</div>\n"
        )
        cleaned = _clean_markdown(raw)
        self.assertNotIn("\x00", cleaned)
        self.assertNotIn("<div", cleaned)
        self.assertIn("| a | b |", cleaned)
        self.assertIn("<!-- page 3 -->", cleaned)
        self.assertIn("text with spaces", cleaned)
        self.assertNotIn("\n\n\n", cleaned)

    def test_output_dir_creates_path(self):
        with TemporaryDirectory() as tmp:
            path = _output_dir(str(Path(tmp) / "nested"))
            self.assertTrue(path.exists())
            self.assertTrue(path.is_dir())


if __name__ == "__main__":
    unittest.main()
