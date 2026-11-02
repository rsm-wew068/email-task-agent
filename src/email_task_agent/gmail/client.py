"""Real Gmail client (private instance): history.list / threads.get /
messages.list, prefiltering, and MIME parsing into SyncThread objects.

Scopes are read/write-draft for Gmail plus calendar/tasks; the refresh token
lives in a local file OUTSIDE the repo (plan §6 note).
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from email.message import EmailMessage

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from email_task_agent.gmail.mime import header_addresses, strip_quoted_replies_and_signature
from email_task_agent.pipeline.sync import HistoryResult, SyncMessage, SyncThread

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/tasks",
]

_SKIP_LABELS = {"TRASH", "SPAM", "CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL"}


def load_credentials(token_path: str) -> Credentials:
    with open(token_path) as fh:
        creds = Credentials(**json.load(fh))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w") as fh:
            fh.write(creds.to_json())
    return creds


def build_gmail(token_path: str):
    return build("gmail", "v1", credentials=load_credentials(token_path))


class GmailClient:
    """Implements the SyncService GmailClientProtocol (plus helpers used by
    the chat tools)."""

    def __init__(self, service, me: str):
        self._service = service
        self._me = me.strip().casefold()

    # -- SyncService protocol --------------------------------------------------------

    def changed_since(self, start_history_id: str) -> HistoryResult:
        try:
            response = self._service.users().history().list(userId="me", startHistoryId=start_history_id).execute()
        except HttpError as error:
            if error.resp.status == 404:
                return HistoryResult(expired=True)
            raise

        changed: dict[str, str] = {}  # gmail_message_id -> history_id
        for record in response.get("history", []):
            history_id = record["id"]
            for entry in record.get("messagesAdded", []):
                message = entry["message"]
                if _SKIP_LABELS & set(message.get("labelIds", [])):
                    continue
                changed[message["id"]] = history_id
            for entry in record.get("messagesDeleted", []):
                changed.pop(entry["message"]["id"], None)

        thread_history: dict[str, str] = {}
        for message_id, history_id in changed.items():
            meta = self._service.users().messages().get(userId="me", id=message_id, format="minimal").execute()
            thread_id = meta["threadId"]
            if thread_id not in thread_history or int(history_id) > int(thread_history[thread_id]):
                thread_history[thread_id] = history_id

        built = [self.fetch_single(tid, history_id=hid) for tid, hid in sorted(thread_history.items(), key=lambda kv: int(kv[1]))]
        return HistoryResult(threads=built, latest_history_id=response.get("historyId"))

    def full_sync(self, days: int) -> HistoryResult:
        query = f"newer_than:{days}d -in:chat -category:promotions -category:social"
        thread_ids: list[str] = []
        page_token = None
        while True:
            response = (
                self._service.users()
                .threads()
                .list(userId="me", q=query, maxResults=100, pageToken=page_token)
                .execute()
            )
            thread_ids.extend(t["id"] for t in response.get("threads", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        profile = self._service.users().getProfile(userId="me").execute()
        latest = profile.get("historyId")
        built = [self.fetch_single(tid, history_id=latest) for tid in thread_ids]
        return HistoryResult(threads=built, latest_history_id=latest)

    def fetch_single(self, gmail_thread_id: str, history_id: str | None = None) -> SyncThread:
        thread = self._service.users().threads().get(userId="me", id=gmail_thread_id, format="full").execute()
        messages: list[SyncMessage] = []
        participants: set[str] = {self._me}
        subject = "(no subject)"
        bodies: list[str] = []

        for raw in thread.get("messages", []):
            if _SKIP_LABELS & set(raw.get("labelIds", [])):
                continue
            payload = raw.get("payload", {})
            headers = {h["name"]: h["value"] for h in payload.get("headers", [])}
            subject = headers.get("Subject") or subject
            sender = (header_addresses(headers.get("From")) or ["unknown@unknown"])[0]
            to_list = header_addresses(headers.get("To"))
            cc_list = header_addresses(headers.get("Cc"))
            participants.update([sender, *to_list, *cc_list])

            body = strip_quoted_replies_and_signature(_decode_body(payload) or "")
            if len(body) > 20_000:
                body = body[:20_000] + "\n[truncated]"

            internal_date = datetime.fromtimestamp(
                int(raw.get("internalDate", "0")) / 1000, tz=UTC
            ) if raw.get("internalDate") else datetime.now(UTC)

            messages.append(
                SyncMessage(
                    message_id=raw["id"],
                    sender=sender,
                    to=to_list,
                    cc=cc_list,
                    internal_date=internal_date,
                    subject=headers.get("Subject") or "(no subject)",
                    body=body,
                )
            )
            bodies.append(f"Subject: {messages[-1].subject}\n\n{body}")

        return SyncThread(
            gmail_thread_id=gmail_thread_id,
            subject=subject,
            participants=sorted(participants),
            messages=messages,
            history_id=history_id or str(thread.get("historyId", "")),
            cached_text="\n\n".join(bodies),
        )

    # -- chat tool helpers ------------------------------------------------------------

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        """messages.list with q= (§8 search_gmail)."""
        response = self._service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        results = []
        for item in response.get("messages", []):
            meta = self._service.users().messages().get(userId="me", id=item["id"], format="metadata").execute()
            headers = {h["name"]: h["value"] for h in meta["payload"].get("headers", [])}
            results.append(
                {
                    "gmail_message_id": item["id"],
                    "thread_id": meta["threadId"],
                    "from": headers.get("From", ""),
                    "subject": headers.get("Subject", ""),
                    "date": headers.get("Date", ""),
                }
            )
        return results

    def create_draft(self, to: str, subject: str, body: str) -> str:
        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        draft = self._service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
        return draft["id"]


def _decode_body(payload: dict) -> str | None:
    """Walk MIME parts; prefer text/plain, fall back to crudely cleaned HTML."""

    def from_data(data: str | None) -> str | None:
        if not data:
            return None
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    mime_type = payload.get("mimeType", "")
    if mime_type == "text/plain":
        text = from_data(payload.get("body", {}).get("data"))
        if text:
            return text
    if mime_type == "text/html":
        text = from_data(payload.get("body", {}).get("data"))
        if text:
            return _html_to_text(text)
    for part in payload.get("parts", []):
        text = _decode_body(part)
        if text:
            return text
    return None


def _html_to_text(html: str) -> str:
    import re

    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", html)
    text = re.sub(r"<[^>]+>", "", text)
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(entity, char)
    return text
