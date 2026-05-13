import os
import smtplib
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services import email_service


def _complaint(**kwargs):
    defaults = dict(id=42, status="pending", department="Water Department")
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestEmailNotifications(unittest.TestCase):
    def test_skip_when_no_recipient(self):
        with patch.dict(os.environ, {"SMTP_HOST": "smtp.example.com"}, clear=False):
            ok = email_service.send_complaint_email(None, "CIVITAS complaint submitted", _complaint())
        self.assertFalse(ok)

    def test_skip_when_smtp_host_missing(self):
        with patch.dict(os.environ, {"SMTP_HOST": ""}, clear=False):
            ok = email_service.send_complaint_email(
                "user@example.com", "CIVITAS complaint submitted", _complaint()
            )
        self.assertFalse(ok)

    @patch("services.email_service.smtplib.SMTP")
    def test_complaint_submitted_email_gmail_style_587(self, mock_smtp):
        mock_instance = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_instance

        env = {
            "SMTP_HOST": "smtp.gmail.com",
            "SMTP_PORT": "587",
            "SMTP_USERNAME": "me@gmail.com",
            "SMTP_PASSWORD": "secret",
            "SMTP_FROM": "me@gmail.com",
            "SMTP_STARTTLS": "true",
            "SMTP_SSL": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            ok = email_service.send_complaint_email(
                "citizen@example.com",
                "CIVITAS complaint submitted",
                _complaint(),
                request=None,
            )
        self.assertTrue(ok)
        mock_instance.starttls.assert_called_once()
        mock_instance.login.assert_called_once_with("me@gmail.com", "secret")
        mock_instance.send_message.assert_called_once()
        msg = mock_instance.send_message.call_args[0][0]
        self.assertEqual(msg["Subject"], "CIVITAS complaint submitted")
        self.assertEqual(msg["To"], "citizen@example.com")

    @patch("services.email_service.smtplib.SMTP_SSL")
    def test_status_update_uses_ssl_on_port_465(self, mock_ssl):
        mock_instance = MagicMock()
        mock_ssl.return_value.__enter__.return_value = mock_instance

        env = {
            "SMTP_HOST": "smtp.gmail.com",
            "SMTP_PORT": "465",
            "SMTP_USERNAME": "me@gmail.com",
            "SMTP_PASSWORD": "secret",
            "SMTP_FROM": "me@gmail.com",
        }
        with patch.dict(os.environ, env, clear=False):
            ok = email_service.send_complaint_email(
                "citizen@example.com",
                "CIVITAS complaint status updated",
                _complaint(status="in_progress"),
                request=None,
            )
        self.assertTrue(ok)
        mock_ssl.assert_called_once()
        mock_instance.starttls.assert_not_called()
        mock_instance.login.assert_called_once()
        msg = mock_instance.send_message.call_args[0][0]
        self.assertEqual(msg["Subject"], "CIVITAS complaint status updated")
        self.assertIn("in_progress", msg.get_payload())

    @patch("services.email_service.smtplib.SMTP")
    def test_resolved_email_subject(self, mock_smtp):
        mock_instance = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_instance

        env = {
            "SMTP_HOST": "smtp.gmail.com",
            "SMTP_PORT": "587",
            "SMTP_USERNAME": "me@gmail.com",
            "SMTP_PASSWORD": "secret",
            "SMTP_FROM": "me@gmail.com",
        }
        with patch.dict(os.environ, env, clear=False):
            ok = email_service.send_complaint_email(
                "citizen@example.com",
                "CIVITAS complaint resolved",
                _complaint(status="resolved"),
                request=None,
            )
        self.assertTrue(ok)
        msg = mock_instance.send_message.call_args[0][0]
        self.assertEqual(msg["Subject"], "CIVITAS complaint resolved")

    @patch("services.email_service.smtplib.SMTP")
    def test_smtp_auth_failure_returns_false_and_does_not_raise(self, mock_smtp):
        mock_instance = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_instance
        mock_instance.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Auth failed")

        env = {
            "SMTP_HOST": "smtp.gmail.com",
            "SMTP_PORT": "587",
            "SMTP_USERNAME": "me@gmail.com",
            "SMTP_PASSWORD": "wrong",
            "SMTP_FROM": "me@gmail.com",
        }
        with patch.dict(os.environ, env, clear=False):
            ok = email_service.send_complaint_email(
                "citizen@example.com",
                "CIVITAS complaint submitted",
                _complaint(),
                request=None,
            )
        self.assertFalse(ok)

    @patch("services.email_service.smtplib.SMTP")
    def test_connection_error_returns_false(self, mock_smtp):
        mock_smtp.side_effect = OSError("Network unreachable")

        env = {
            "SMTP_HOST": "smtp.gmail.com",
            "SMTP_PORT": "587",
            "SMTP_USERNAME": "me@gmail.com",
            "SMTP_PASSWORD": "secret",
            "SMTP_FROM": "me@gmail.com",
        }
        with patch.dict(os.environ, env, clear=False):
            ok = email_service.send_complaint_email(
                "citizen@example.com",
                "CIVITAS complaint submitted",
                _complaint(),
                request=None,
            )
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
