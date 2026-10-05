import io
import json
import logging

from django.test import SimpleTestCase
from django.test.client import RequestFactory

from manuspectrum.observability import logging as obs_logging
from manuspectrum.observability.context import bound_request_id
from tests.observability_helpers import delta

LOGGER = "manuspectrum.obs-test"


def emit(fmt, *args, level=logging.WARNING, exc_info=None, **extra):
    """Log one record on a private logger wired like build_logging's handlers; its output."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(obs_logging.RequestIdFilter())
    handler.setFormatter(
        obs_logging.JsonFormatter(environment="test", version="1.2.3")
        if fmt == "json"
        else obs_logging.TextFormatter()
    )
    counter = obs_logging.LogRecordCounter(level=logging.WARNING)
    logger = logging.getLogger(LOGGER)
    logger.handlers, logger.propagate = [handler, counter], False
    logger.setLevel(logging.DEBUG)
    try:
        logger.log(level, *args, exc_info=exc_info, extra=extra or None)
    finally:
        logger.handlers = []
    return stream.getvalue().strip()


class JsonFormatterTests(SimpleTestCase):
    def test_the_six_mandatory_fields_and_the_recommended_ones(self):
        with bound_request_id("abcdef0123456789"):
            record = json.loads(emit("json", "hello %s", "world"))
        self.assertEqual(record["message"], "hello world")
        self.assertEqual(record["level"], "WARNING")
        self.assertEqual(record["service"], "manuspectrum")
        self.assertEqual(record["request_id"], "abcdef0123456789")
        self.assertEqual(record["trace_id"], "")
        self.assertRegex(
            record["timestamp"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+\+00:00$"
        )
        self.assertEqual(record["logger"], LOGGER)
        self.assertEqual(record["environment"], "test")
        self.assertEqual(record["version"], "1.2.3")
        self.assertTrue(record["hostname"])

    def test_request_id_is_empty_outside_a_request(self):
        self.assertEqual(json.loads(emit("json", "x"))["request_id"], "")

    def test_extra_fields_are_kept_and_the_request_object_is_dropped(self):
        request = RequestFactory().get("/en/x?password=hunter2")
        request.request_id = "fromrequest0001"
        record = json.loads(emit("json", "Not Found", status_code=404, request=request))
        self.assertEqual(record["status_code"], 404)
        self.assertNotIn("request", record)
        self.assertNotIn("hunter2", json.dumps(record))
        self.assertEqual(record["request_id"], "fromrequest0001")

    def test_one_line_per_record_even_with_a_traceback(self):
        try:
            raise RuntimeError("boom\nsecond line")
        except RuntimeError:
            output = emit("json", "failed", level=logging.ERROR, exc_info=True)
        lines = output.splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("RuntimeError", json.loads(lines[0])["exc_info"])


class RedactionTests(SimpleTestCase):
    def test_text_patterns(self):
        cases = {
            "write to ops@example.org now": "write to [email] now",
            "Authorization: Bearer abc.def": "Authorization: [redacted]",
            "token msiiif1.AbC-12_x.y refused": "token [redacted] refused",
            "GET /x?password=hunter2&q=1": "GET /x?password=[redacted]&q=1",
            "csrftoken=abc; sessionid=def": "csrftoken=[redacted]; sessionid=[redacted]",
            "redis://:s3cret@redis-cache:6379/0 down": "redis://[redacted]@redis-cache:6379/0 down",
            "nothing to hide": "nothing to hide",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(obs_logging.redact_text(text), expected)

    def test_sensitive_keys_are_masked_in_nested_extras(self):
        value = {
            "password": "x",
            "nested": {"api_key": "y", "language": "fr"},
            "cookie": "z",
        }
        self.assertEqual(
            obs_logging.redact(value),
            {
                "password": "[redacted]",
                "nested": {"api_key": "[redacted]", "language": "fr"},
                "cookie": "[redacted]",
            },
        )

    def test_a_record_is_redacted_in_json_and_in_text(self):
        record = json.loads(emit("json", "user %s", "a@b.org", session_token="t0k"))
        self.assertEqual(record["message"], "user [email]")
        self.assertEqual(record["session_token"], "[redacted]")
        self.assertIn("user [email]", emit("text", "user %s", "a@b.org"))

    def test_text_format_carries_the_request_id(self):
        with bound_request_id("textid000000001"):
            self.assertIn("[textid000000001]", emit("text", "x"))


class LogRecordCounterTests(SimpleTestCase):
    def test_warning_and_above_are_counted_by_source_info_is_not(self):
        with (
            delta(
                "manuspectrum_log_records_total", level="error", source="manuspectrum"
            ) as errors,
            delta(
                "manuspectrum_log_records_total", level="warning", source="manuspectrum"
            ) as warnings,
        ):
            emit("json", "w")
            emit("json", "e", level=logging.ERROR)
            emit("json", "i", level=logging.INFO)
        self.assertEqual((errors.value, warnings.value), (1, 1))


class BuildLoggingTests(SimpleTestCase):
    def test_every_configured_logger_writes_to_the_console_and_the_counter(self):
        config = obs_logging.build_logging("json", environment="t", version="v")
        self.assertEqual(config["root"]["handlers"], ["console", "metrics"])
        for name, logger in config["loggers"].items():
            with self.subTest(logger=name):
                self.assertEqual(logger["handlers"], ["console", "metrics"])
                self.assertFalse(logger["propagate"])
        self.assertEqual(config["handlers"]["console"]["stream"], "ext://sys.stdout")
        self.assertEqual(config["loggers"]["django.request"]["level"], "WARNING")

    def test_unknown_format_is_refused(self):
        with self.assertRaises(ValueError):
            obs_logging.build_logging("xml", environment="t", version="v")
