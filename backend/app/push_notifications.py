"""Privacy-safe Firebase Cloud Messaging delivery for the MongoDB platform."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

EVENTS = frozenset({
    "chat.message", "class.created", "class.updated", "class.deleted",
    "relation.created", "relation.updated", "relation.deleted",
    "diagram.xmi_imported", "ai.done", "ai.error", "ai.endpoints",
})
MAX_TOKENS_PER_MESSAGE = 500
MAX_TOKEN_LENGTH = 4096


class PushNotifications:
    def __init__(self, *, sender: Any = None, credentials_path: str | None = None):
        self.sender = sender
        self.enabled = sender is not None
        self._firebase = None
        path = credentials_path if credentials_path is not None else os.getenv("FIREBASE_CREDENTIALS_PATH")
        if self.enabled or not path:
            return
        try:
            if not Path(path).is_file():
                return
            import firebase_admin
            from firebase_admin import credentials, messaging

            try:
                app = firebase_admin.get_app()
            except ValueError:
                app = firebase_admin.initialize_app(credentials.Certificate(path))
            self._firebase = (messaging, app)
            self.sender = self._send_firebase
            self.enabled = True
        except Exception:
            # Configuration errors must never prevent the platform from starting.
            self.enabled = False

    def _send_firebase(self, tokens: list[str], data: dict[str, str], title: str, body: str):
        messaging, app = self._firebase
        message = messaging.MulticastMessage(
            tokens=tokens, data=data,
            notification=messaging.Notification(title=title, body=body),
        )
        return messaging.send_each_for_multicast(message, app=app)

    @staticmethod
    def _recipients(diagram: dict, excluded_user_id: Any = None) -> set[int]:
        recipients = {int(diagram["owner_id"])}
        recipients.update(int(member["user_id"]) for member in diagram.get("members", []) if member.get("active", True))
        if excluded_user_id is not None:
            try:
                recipients.discard(int(excluded_user_id))
            except (TypeError, ValueError):
                pass
        return recipients

    async def publish(self, store, diagram_id: str, event: dict) -> None:
        if not self.enabled or event.get("event") not in EVENTS:
            return
        try:
            await asyncio.to_thread(self._publish_sync, store, diagram_id, event)
        except Exception:
            return

    def _publish_sync(self, store, diagram_id: str, event: dict) -> None:
        diagram = store.diagram_by_id(diagram_id)
        if not diagram:
            return
        actor = event.get("initiator_user_id", event.get("actor_user_id"))
        message = event.get("message")
        if actor is None and isinstance(message, dict):
            actor = message.get("author_user_id")
        if actor is None and event.get("event") == "ai.done" and event.get("trigger_id"):
            trigger = store.chat_messages.find_one({"id": str(event["trigger_id"])}, {"author_user_id": True})
            if trigger:
                actor = trigger.get("author_user_id")
        recipient_ids = self._recipients(diagram, actor)
        if not recipient_ids:
            return
        tokens = store.device_tokens_for_users(recipient_ids)
        if not tokens:
            return
        data = {"diagram_id": str(diagram_id), "event": str(event["event"])}
        for start in range(0, len(tokens), MAX_TOKENS_PER_MESSAGE):
            batch = tokens[start:start + MAX_TOKENS_PER_MESSAGE]
            try:
                result = self.sender(
                    [item["token"] for item in batch], data,
                    "Actualización del equipo", "Hay nueva actividad en un diagrama.",
                )
            except Exception:
                continue
            responses = getattr(result, "responses", ())
            for registration, response in zip(batch, responses):
                if getattr(response, "success", True):
                    continue
                error_code = getattr(getattr(response, "exception", None), "code", "")
                if error_code in {"messaging/invalid-registration-token", "messaging/registration-token-not-registered"}:
                    store.delete_device_token(registration["token"])


push_notifications = PushNotifications()
