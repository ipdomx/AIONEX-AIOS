from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

from .kernel import AIOSKernel


class TelegramInterface:
    def __init__(self, kernel: AIOSKernel):
        token = os.environ.get('AIOS_TELEGRAM_TOKEN')
        if not token:
            raise RuntimeError('AIOS_TELEGRAM_TOKEN is not set')
        self.base = f'https://api.telegram.org/bot{token}'
        allowed = os.environ.get('AIOS_TELEGRAM_ALLOWED_USERS', '')
        self.allowed = {int(x.strip()) for x in allowed.split(',') if x.strip().isdigit()}
        self.kernel = kernel

    def call(self, method: str, data: dict | None = None) -> dict:
        encoded = urllib.parse.urlencode(data or {}).encode()
        with urllib.request.urlopen(f'{self.base}/{method}', encoded, timeout=60) as response:
            return json.loads(response.read().decode())

    def send(self, chat_id: int, text: str) -> None:
        self.call('sendMessage', {'chat_id': chat_id, 'text': text[:4000]})

    def run(self) -> None:
        offset = 0
        while True:
            result = self.call('getUpdates', {'timeout': 40, 'offset': offset})
            for update in result.get('result', []):
                offset = update['update_id'] + 1
                message = update.get('message') or {}
                user_id = (message.get('from') or {}).get('id')
                chat_id = (message.get('chat') or {}).get('id')
                text = message.get('text', '').strip()
                if not user_id or not chat_id:
                    continue
                if self.allowed and user_id not in self.allowed:
                    self.send(chat_id, 'غير مصرح لك باستخدام AIOS.')
                    continue
                if text == '/status':
                    reply = json.dumps(self.kernel.status(), ensure_ascii=False, indent=2)
                elif text == '/projects':
                    reply = json.dumps(self.kernel.projects.list(), ensure_ascii=False, indent=2)
                else:
                    reply = self.kernel.chat(text)
                self.send(chat_id, reply)
            time.sleep(1)


def main() -> None:
    TelegramInterface(AIOSKernel()).run()
