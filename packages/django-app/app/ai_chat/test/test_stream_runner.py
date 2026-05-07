"""Tests for the stream-runner background-thread / tail-loop machinery
that powers chat reload resume (#118)."""

import threading
import time
from typing import Iterator

from django.test import TransactionTestCase

from ai_chat.models import ChatMessage
from ai_chat.services import stream_runner
from ai_chat.services.base_ai_service import AIUsage
from ai_chat.services.stream_runner import (
    StreamRunnerInputs,
    follow_message,
    run_stream_in_thread,
)
from core.test.helpers import UserFactory

from ai_chat.test.helpers import ChatSessionFactory


class FakeAIService:
    """Yields a pre-canned event sequence to drive the worker.

    A small sleep between yields gives the tail loop a chance to read
    intermediate state, mirroring the pacing of a real LLM stream.
    """

    def __init__(self, events, per_event_delay=0.0):
        self._events = list(events)
        self._delay = per_event_delay

    def stream_message(
        self, messages, tools, *, system, tool_executor, response_format=None
    ) -> Iterator[dict]:
        for ev in self._events:
            if self._delay:
                time.sleep(self._delay)
            yield ev


class TestFollowMessageImmediateComplete(TransactionTestCase):
    """When the message is already in 'complete' state, follow_message
    should yield current content + a done event without polling."""

    def test_yields_content_and_done(self):
        user = UserFactory()
        session = ChatSessionFactory(user=user)
        msg = ChatMessage.objects.create(
            session=session,
            role="assistant",
            content="hello world",
            status=ChatMessage.STATUS_COMPLETE,
        )

        events = list(follow_message(str(msg.uuid)))
        types = [e["type"] for e in events]
        self.assertIn("text", types)
        self.assertIn("done", types)
        text_event = next(e for e in events if e["type"] == "text")
        self.assertEqual(text_event["delta"], "hello world")

    def test_error_status_yields_error(self):
        user = UserFactory()
        session = ChatSessionFactory(user=user)
        msg = ChatMessage.objects.create(
            session=session,
            role="assistant",
            content="partial result",
            status=ChatMessage.STATUS_ERROR,
        )

        events = list(follow_message(str(msg.uuid)))
        self.assertEqual(events[-1]["type"], "error")
        # The pre-error content still rides along so the user sees what
        # was generated before the failure.
        text_event = next((e for e in events if e["type"] == "text"), None)
        self.assertIsNotNone(text_event)
        self.assertEqual(text_event["delta"], "partial result")

    def test_missing_message_yields_error(self):
        events = list(follow_message("00000000-0000-0000-0000-000000000000"))
        self.assertEqual(events[-1]["type"], "error")


class TestRunStreamInThread(TransactionTestCase):
    """Drive the worker thread end-to-end with a fake AI service and
    confirm the message row reaches the expected terminal state."""

    def test_text_then_done_finalizes_message(self):
        user = UserFactory()
        session = ChatSessionFactory(user=user)
        msg = ChatMessage.objects.create(
            session=session,
            role="assistant",
            content="",
            status=ChatMessage.STATUS_STREAMING,
        )

        fake = FakeAIService(
            [
                {"type": "text", "delta": "hello "},
                {"type": "text", "delta": "world"},
                {
                    "type": "done",
                    "content": "hello world",
                    "thinking": "",
                    "usage": AIUsage(input_tokens=12, output_tokens=4),
                    "tool_events": [],
                },
            ]
        )

        thread = run_stream_in_thread(
            assistant_message=msg,
            inputs=StreamRunnerInputs(
                service=fake,
                messages=[],
                tools=[],
                tool_executor=None,
                system="ignored",
            ),
        )
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive(), "worker thread should have finished")

        msg.refresh_from_db()
        self.assertEqual(msg.status, ChatMessage.STATUS_COMPLETE)
        self.assertEqual(msg.content, "hello world")
        self.assertEqual(msg.input_tokens, 12)
        self.assertEqual(msg.output_tokens, 4)

    def test_exception_marks_message_error(self):
        user = UserFactory()
        session = ChatSessionFactory(user=user)
        msg = ChatMessage.objects.create(
            session=session,
            role="assistant",
            content="",
            status=ChatMessage.STATUS_STREAMING,
        )

        class Boom:
            def stream_message(self, *args, **kwargs):
                yield {"type": "text", "delta": "before crash "}
                raise RuntimeError("simulated provider failure")

        thread = run_stream_in_thread(
            assistant_message=msg,
            inputs=StreamRunnerInputs(
                service=Boom(),
                messages=[],
                tools=[],
                tool_executor=None,
                system="ignored",
            ),
        )
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())

        msg.refresh_from_db()
        self.assertEqual(msg.status, ChatMessage.STATUS_ERROR)
        self.assertIn("before crash", msg.content)


class TestFollowMessageStaleDetection(TransactionTestCase):
    """A streaming row that nobody is updating should eventually be
    declared dead so a follower doesn't tail it forever."""

    def test_stale_streaming_row_is_promoted_to_error(self):
        user = UserFactory()
        session = ChatSessionFactory(user=user)
        msg = ChatMessage.objects.create(
            session=session,
            role="assistant",
            content="started",
            status=ChatMessage.STATUS_STREAMING,
        )

        # Tighten the staleness window for the test so we don't have to
        # wait the full 90s default. The patch is reverted in finally.
        original_threshold = stream_runner.STALE_THRESHOLD_SECONDS
        original_poll = stream_runner.POLL_INTERVAL_SECONDS
        stream_runner.STALE_THRESHOLD_SECONDS = 0.2
        stream_runner.POLL_INTERVAL_SECONDS = 0.05
        try:
            events = list(follow_message(str(msg.uuid)))
        finally:
            stream_runner.STALE_THRESHOLD_SECONDS = original_threshold
            stream_runner.POLL_INTERVAL_SECONDS = original_poll

        self.assertEqual(events[-1]["type"], "error")
        msg.refresh_from_db()
        self.assertEqual(msg.status, ChatMessage.STATUS_ERROR)


class TestFollowMessageReadsLiveUpdates(TransactionTestCase):
    """End-to-end check that a follower picks up worker-thread writes."""

    def test_follower_sees_worker_text_deltas(self):
        user = UserFactory()
        session = ChatSessionFactory(user=user)
        msg = ChatMessage.objects.create(
            session=session,
            role="assistant",
            content="",
            status=ChatMessage.STATUS_STREAMING,
        )

        fake = FakeAIService(
            [
                {"type": "text", "delta": "alpha "},
                {"type": "text", "delta": "beta"},
                {
                    "type": "done",
                    "content": "alpha beta",
                    "thinking": "",
                    "usage": AIUsage(),
                    "tool_events": [],
                },
            ],
            per_event_delay=0.05,
        )

        # Tight poll cadence so the test runs quickly.
        original_poll = stream_runner.POLL_INTERVAL_SECONDS
        stream_runner.POLL_INTERVAL_SECONDS = 0.02
        try:
            collected = []

            def follower():
                for ev in follow_message(str(msg.uuid)):
                    collected.append(ev)

            t_follow = threading.Thread(target=follower)
            t_follow.start()

            run_stream_in_thread(
                assistant_message=msg,
                inputs=StreamRunnerInputs(
                    service=fake,
                    messages=[],
                    tools=[],
                    tool_executor=None,
                    system="ignored",
                ),
            )
            t_follow.join(timeout=5)
        finally:
            stream_runner.POLL_INTERVAL_SECONDS = original_poll

        text_deltas = [e for e in collected if e["type"] == "text"]
        joined = "".join(e.get("delta", "") for e in text_deltas)
        self.assertIn("alpha", joined)
        self.assertIn("beta", joined)
        self.assertEqual(collected[-1]["type"], "done")
