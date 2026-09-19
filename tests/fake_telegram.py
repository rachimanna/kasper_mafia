"""Поддельный Telegram Bot API для интеграционных тестов."""
import itertools
import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from aiohttp import web


@dataclass
class Sent:
    chat_id: int
    message_id: int
    text: str
    markup: Optional[dict]
    history: List[str] = field(default_factory=list)


class FakeTelegram:
    def __init__(self) -> None:
        self.messages: Dict[tuple, Sent] = {}
        self.by_chat: Dict[int, List[Sent]] = {}
        self.deleted: List[tuple] = []
        self.callback_answers: List[dict] = []
        self.ids = itertools.count(1)
        self.admins: set = set()
        self.calls: List[str] = []

    def chat(self, chat_id: int) -> dict:
        return {"id": chat_id, "type": "private" if chat_id > 0 else "supergroup",
                **({"first_name": f"U{chat_id}"} if chat_id > 0 else {"title": "Test Group"})}

    def msg_json(self, s: Sent) -> dict:
        d = {"message_id": s.message_id, "date": int(time.time()), "chat": self.chat(s.chat_id), "text": s.text}
        if s.markup:
            d["reply_markup"] = s.markup
        return d

    async def handle(self, request: web.Request) -> web.Response:
        method = request.match_info["method"]
        data = dict(await request.post()) if request.can_read_body else {}
        self.calls.append(method)
        markup = json.loads(data["reply_markup"]) if data.get("reply_markup") else None
        result = True
        if method == "getMe":
            result = {"id": 999, "is_bot": True, "first_name": "Mafia", "username": "test_mafia_bot"}
        elif method == "sendMessage":
            chat_id = int(data["chat_id"])
            s = Sent(chat_id, next(self.ids), data["text"], markup)
            self.messages[(chat_id, s.message_id)] = s
            self.by_chat.setdefault(chat_id, []).append(s)
            result = self.msg_json(s)
        elif method in ("editMessageText", "editMessageReplyMarkup"):
            key = (int(data["chat_id"]), int(data["message_id"]))
            s = self.messages[key]
            if method == "editMessageText":
                s.history.append(s.text)
                s.text = data["text"]
            s.markup = markup
            result = self.msg_json(s)
        elif method == "deleteMessage":
            self.deleted.append((int(data["chat_id"]), int(data["message_id"])))
        elif method == "answerCallbackQuery":
            self.callback_answers.append(data)
        elif method == "getChatMember":
            uid = int(data["user_id"])
            if uid in self.admins:
                result = {"status": "creator", "is_anonymous": False,
                          "user": {"id": uid, "is_bot": False, "first_name": f"U{uid}"}}
            else:
                result = {"status": "member", "user": {"id": uid, "is_bot": False, "first_name": f"U{uid}"}}
        return web.json_response({"ok": True, "result": result})

    async def start(self, port: int) -> web.AppRunner:
        app = web.Application()
        app.router.add_post("/bot{token}/{method}", self.handle)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", port).start()
        return runner
