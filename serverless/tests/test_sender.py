import importlib.util
import json
from email import policy
from email.parser import BytesParser
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location(
    "email_sender", Path(__file__).parents[1] / "send-email.py"
)
sender = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sender)


class SenderTests(unittest.TestCase):
    def setUp(self):
        self.config = patch.multiple(
            sender,
            EMAIL_FROM="noreply@l4desk.ru",
            EMAIL_FROM_PL="noreply@platerra.ru",
            ACCESS_KEY_ID="test-only",
            SECRET_ACCESS_KEY="test-only",
        )
        self.config.start()
        self.addCleanup(self.config.stop)
        self.client = Mock()
        self.client.send_email.return_value = {"MessageId": "test-message-id"}

    def test_sender_matches_raw_header_and_postbox_envelope(self):
        for channel, address in [
            ("platerra-landing", "noreply@platerra.ru"),
            ("l4desk-landing", "noreply@l4desk.ru"),
            ("terminal-123", "noreply@platerra.ru"),
            ("another-project", "noreply@platerra.ru"),
            ("l4desk-landing-other", "noreply@platerra.ru"),
        ]:
            with (
                self.subTest(channel=channel),
                patch.object(sender.boto3, "client", return_value=self.client),
            ):
                sender.send_email_with_attachment(
                    ["info@platerra.ru"], channel, subject="Test", message="Hello"
                )
                payload = self.client.send_email.call_args.kwargs
                raw = BytesParser(policy=policy.default).parsebytes(
                    payload["Content"]["Raw"]["Data"]
                )
                self.assertEqual(payload["FromEmailAddress"], address)
                self.assertEqual(str(raw["From"]), address)

    def test_empty_suffix_is_rejected(self):
        for channel in [None, "", "   "]:
            with self.subTest(channel=channel), self.assertRaises(ValueError):
                sender.resolve_email_sender(channel)

    def test_missing_platerra_sender_does_not_fall_back_to_l4desk(self):
        with (
            patch.object(sender, "EMAIL_FROM_PL", ""),
            patch.object(sender.boto3, "client") as client,
        ):
            for channel in ["platerra-landing", "terminal-123", "another-project"]:
                with (
                    self.subTest(channel=channel),
                    self.assertRaisesRegex(RuntimeError, "L4_EMAIL_FROM_PLATERRA"),
                ):
                    sender.send_email_with_attachment(["info@platerra.ru"], channel)
            client.assert_not_called()
            self.assertEqual(
                sender.resolve_email_sender("l4desk-landing"), "noreply@l4desk.ru"
            )

    def test_untrusted_sender_field_cannot_override_server_selection(self):
        event = {
            "httpMethod": "POST",
            "pathParams": {"device_id": "platerra-landing"},
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(
                {
                    "recipients": ["info@platerra.ru"],
                    "subject": "Test",
                    "message": "Hello",
                    "sender": "attacker@example.com",
                }
            ),
        }
        with patch.object(sender.boto3, "client", return_value=self.client):
            result = sender.handler(event, None)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(json.loads(result["body"])["sender"], "noreply@platerra.ru")
        self.assertEqual(
            self.client.send_email.call_args.kwargs["FromEmailAddress"],
            "noreply@platerra.ru",
        )


if __name__ == "__main__":
    unittest.main()
