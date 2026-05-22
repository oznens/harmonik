"""Telegram chat_id keşif yardımcısı.

Kullanım:
    1. Telegram'da bot'a /start yaz (veya herhangi bir mesaj).
    2. python -m terminal.cli.tg_setup
    3. Script son gelen mesajdan chat_id'i okur ve .env'e yazar.
"""
from __future__ import annotations

import sys
from pathlib import Path

from terminal.config import PROJECT_ROOT, TELEGRAM_BOT_TOKEN
from terminal.telegram_bot.client import TelegramClient, TelegramError


def main() -> int:
    if not TELEGRAM_BOT_TOKEN:
        print("HATA: .env dosyasında TELEGRAM_BOT_TOKEN yok.", file=sys.stderr)
        return 1

    try:
        client = TelegramClient()
        me = client.get_me()
        print(f"Bot: @{me['username']} ({me['first_name']})")
        print()

        updates = client.get_updates(timeout=1)
        if not updates:
            print("Henüz mesaj yok.")
            print(f"  1. Telegram'da @{me['username']} bot'unu aç,")
            print(f"  2. /start veya herhangi bir mesaj gönder,")
            print(f"  3. Bu komutu tekrar çalıştır.")
            client.close()
            return 1

        # En son mesajdan chat_id al
        chats: dict[int, dict] = {}
        for u in updates:
            msg = u.get("message") or u.get("edited_message") or u.get("channel_post") or {}
            chat = msg.get("chat") or {}
            cid = chat.get("id")
            if cid is None:
                continue
            chats[cid] = {
                "type": chat.get("type"),
                "title": chat.get("title") or chat.get("username") or chat.get("first_name"),
            }

        if not chats:
            print("Mesaj bulundu ama chat bilgisi okunamadı.", file=sys.stderr)
            client.close()
            return 1

        print("Bulunan chat(ler):")
        for cid, info in chats.items():
            print(f"  chat_id={cid}  type={info['type']}  name={info['title']}")
        print()

        # Tek chat varsa otomatik yaz; çoksa kullanıcıya sor
        if len(chats) == 1:
            chat_id = next(iter(chats))
        else:
            ans = input("Hangi chat_id'i .env'e yazayım? ").strip()
            chat_id = int(ans)

        _write_chat_id_to_env(chat_id)
        print(f".env güncellendi: TELEGRAM_CHAT_ID={chat_id}")
        print()

        # Doğrulama: bu chat'e test mesajı gönder
        print("Test mesajı gönderiliyor...")
        client.send_message("✅ terminalMiraz Telegram bağlantısı çalışıyor.", chat_id=str(chat_id))
        print("Tamam — Telegram'a bak.")
        client.close()
        return 0
    except TelegramError as e:
        print(f"Telegram hatası: {e}", file=sys.stderr)
        return 1


def _write_chat_id_to_env(chat_id: int) -> None:
    env_path = PROJECT_ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    out: list[str] = []
    found = False
    for line in lines:
        if line.startswith("TELEGRAM_CHAT_ID="):
            out.append(f"TELEGRAM_CHAT_ID={chat_id}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"TELEGRAM_CHAT_ID={chat_id}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
