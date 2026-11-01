"""A span processor that masks secrets before spans reach any exporter (S9, R-16).

Instrumentation libraries set attributes we do not control (URLs with query
strings, SQL text, exception messages), and they set many of them after the span
starts. So redaction happens when the span ends: the processor builds a scrubbed
copy of the finished span and hands only that copy to the exporting processor.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from opentelemetry.context import Context
from opentelemetry.sdk.trace import Event, ReadableSpan, Span, SpanProcessor
from opentelemetry.trace import Link, Status
from opentelemetry.util.types import Attributes, AttributeValue

from homelab_harness.redaction import Redactor, redactor


class RedactingSpanProcessor(SpanProcessor):
    """Wrap an exporting span processor so it only ever sees redacted spans.

    The span name, status description, attributes, event attributes (exception
    messages and stack traces live there) and link attributes all pass through
    the shared redactor: sensitive keys are masked whatever their value, and
    registered secret values are masked wherever they appear.
    """

    def __init__(self, inner: SpanProcessor, target: Redactor = redactor) -> None:
        """Wrap ``inner``.

        Args:
            inner: The processor that exports (batch in production, simple in tests).
            target: The redactor to apply; the process-wide one by default.
        """
        self._inner = inner
        self._redactor = target

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        """Pass through: nothing is exported at start."""
        self._inner.on_start(span, parent_context=parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        """Hand a redacted copy of the finished span to the inner processor."""
        self._inner.on_end(self._scrubbed(span))

    def shutdown(self) -> None:
        """Shut down the inner processor, flushing what it holds."""
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Flush the inner processor.

        Args:
            timeout_millis: Upper bound on the flush.

        Returns:
            Whether the flush completed in time.
        """
        return self._inner.force_flush(timeout_millis)

    def _scrubbed(self, span: ReadableSpan) -> ReadableSpan:
        scrub_text = self._redactor.scrub_text
        status = span.status
        return ReadableSpan(
            name=scrub_text(span.name),
            context=span.context,
            parent=span.parent,
            resource=span.resource,
            attributes=self._attributes(span.attributes),
            events=[
                Event(e.name, self._attributes(e.attributes), timestamp=e.timestamp)
                for e in span.events
            ],
            links=[Link(link.context, self._attributes(link.attributes)) for link in span.links],
            kind=span.kind,
            status=Status(
                status.status_code,
                scrub_text(status.description) if status.description else None,
            ),
            start_time=span.start_time,
            end_time=span.end_time,
            instrumentation_scope=span.instrumentation_scope,
        )

    def _attributes(self, attributes: Attributes) -> dict[str, AttributeValue]:
        if not attributes:
            return {}
        scrubbed = self._redactor.scrub(dict(attributes))
        # scrub() turns tuples into lists, which OTel accepts as attribute values.
        return dict(cast(Mapping[str, AttributeValue], scrubbed))
