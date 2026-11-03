"""MIME -> clean thread text (Load stage): MIME to text, strip quoted
replies and signatures, keep bodies bounded."""

from __future__ import annotations

import email
import email.policy
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

_QUOTED_REPLY_RE = re.compile(r"^(on .+wrote:|from:\s.*sent:.*|_{5,|-{5,})\s*$", re.IGNORECASE | re.MULTILINE)
_SIGNATURE_RE = re.compile(r"\n--\s*\n")
_MAX_BODY_CHARS = 20_000


def strip_quoted_replies_and_signature(body: str) -> str:
    if not body:
        return ""
    if match := _SIGNATURE_RE.search(body):
        body = body[: match.start()]
    if match := _QUOTED_REPLY_RE.search(body):
        body = body[: match.start()]
    return body.strip()


def _decode_part(part) -> str | None:
    content_type = part.get_content_type()
    if content_type == "text/plain":
        return part.get_content()
    if content_type == "text/html":
        # Crude HTML-to-text: block tags to newlines, drop tags, unescape entities.
        html = part.get_content()
        text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", html)
        text = re.sub(r"<[^>]+>", "", text)
        text = (
            text.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
        )
        return text
    return None


def message_body_text(raw_bytes: bytes) -> tuple[str, str | None]:
    """Return (subject, body). Prefers text/plain; falls back to crudely
    converted text/html."""
    message = email.message_from_bytes(raw_bytes, policy=email.policy.default)
    subject = message.get("subject")
    plain, html_text = None, None
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() != "text" or part.is_multipart():
                continue
            try:
                content = _decode_part(part)
            except (LookupError, UnicodeDecodeError):
                continue
            if content is None:
                continue
            disposition = (part.get_content_disposition() or "").casefold()
            if disposition == "attachment":
                continue
            if part.get_content_type() == "text/plain" and plain is None:
                plain = content
            elif part.get_content_type() == "text/html" and html_text is None:
                html_text = content
    else:
        try:
            content = _decode_part(message)
        except (LookupError, UnicodeDecodeError):
            content = None
        if message.get_content_type() == "text/plain":
            plain = content
        else:
            html_text = content

    body = plain if plain is not None else (html_text or "")
    body = strip_quoted_replies_and_signature(body)
    if len(body) > _MAX_BODY_CHARS:
        body = body[:_MAX_BODY_CHARS] + "\n[truncated]"
    return subject or "(no subject)", body


def header_addresses(value: str | None) -> list[str]:
    if not value:
        return []
    from email.headerregistry import AddressHeader  # noqa: F401  (policy.default already parses)

    addresses = []
    for token in value.split(","):
        token = token.strip()
        match = re.search(r"<([^<>]+)>", token)
        addresses.append((match.group(1) if match else token).strip().casefold())
    return [a for a in addresses if a and "@" in a]


def parse_internal_date(message) -> datetime:
    raw = message.get("date")
    if raw:
        try:
            parsed = parsedate_to_datetime(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed
        except (TypeError, ValueError):
            pass
    return datetime.now(UTC)
