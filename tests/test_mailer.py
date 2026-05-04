import importlib
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


class _ResponseObject:
    def __init__(self, value=None, data=None):
        self.id = value
        self.data = data


class MailerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules.setdefault("resend", types.SimpleNamespace(Emails=types.SimpleNamespace(send=None)))
        cls.mailer = importlib.import_module("mailer")

    def test_response_id_supports_dict(self):
        self.assertEqual(self.mailer._response_id({"id": "email_123"}), "email_123")

    def test_response_id_supports_object_attribute(self):
        self.assertEqual(self.mailer._response_id(_ResponseObject(value="email_456")), "email_456")

    def test_response_id_supports_nested_data_dict(self):
        self.assertEqual(
            self.mailer._response_id(_ResponseObject(data={"id": "email_789"})),
            "email_789",
        )

    def test_response_id_falls_back_to_unknown(self):
        self.assertEqual(self.mailer._response_id(object()), "unknown")

    def test_send_report_calls_resend_with_attachment(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(b"%PDF-1.4 test")
            pdf_path = tmp.name

        config = {
            "user": {"name": "monitor-a"},
            "topics": ["protein folding"],
            "email": {"recipient": "user@example.com", "from": "Monitor <sender@example.com>"},
        }

        try:
            with patch.dict(os.environ, {"RESEND_API_KEY": "re_test"}, clear=False):
                with patch.object(
                    self.mailer.resend.Emails,
                    "send",
                    return_value={"id": "email_123"},
                ) as mock_send:
                    self.mailer.send_report(pdf_path, 2, config, "2026-03-30")
        finally:
            os.remove(pdf_path)

        params = mock_send.call_args.args[0]
        self.assertEqual(params["to"], ["user@example.com"])
        self.assertEqual(params["attachments"][0]["filename"], os.path.basename(pdf_path))
        self.assertTrue(params["attachments"][0]["content"])

    def test_send_empty_notification_skips_without_api_key(self):
        config = {
            "user": {"name": "monitor-a"},
            "topics": ["protein folding"],
            "email": {"recipient": "user@example.com", "from": "Monitor <sender@example.com>"},
        }

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(self.mailer.resend.Emails, "send") as mock_send:
                self.mailer.send_empty_notification(config, "2026-03-30")

        mock_send.assert_not_called()
