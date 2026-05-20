import discord
from discord.ext import tasks
import requests
from bs4 import BeautifulSoup
import hashlib
import os
import re
import random
import asyncio
import json
import traceback

from dotenv import load_dotenv

load_dotenv()

# =========================
# 環境変数
# =========================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))

# JSON文字列から監視対象を取得
MONITORED_SITES_JSON = os.getenv("MONITORED_SITES", "[]")

try:
    MONITORED_SITES = json.loads(MONITORED_SITES_JSON)
except Exception as e:
    print("MONITORED_SITES の読み込みに失敗しました")
    print(e)
    MONITORED_SITES = []

# =========================
# フォールバック
# =========================

if not DISCORD_TOKEN or CHANNEL_ID == 0:
    try:
        from config import (
            DISCORD_TOKEN,
            CHANNEL_ID,
            CHECK_INTERVAL,
            MONITORED_SITES
        )

        print("config.py を読み込みました")

    except ImportError:
        print("エラー: 環境変数またはconfig.pyが必要です")

client: discord.Client | None = None


# =========================
# Discord Client
# =========================

def create_client() -> discord.Client:

    intents = discord.Intents.default()
    intents.message_content = True

    return discord.Client(intents=intents)


# =========================
# Web監視
# =========================

def get_page_hash(url):
    """ページ内容のハッシュを取得"""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Referer": "https://www.google.com/",
            "Connection": "keep-alive",
        }

        session = requests.Session()

        response = session.get(
            url,
            headers=headers,
            timeout=20,
            allow_redirects=True,
        )

        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup(["script", "style"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)

        return hashlib.md5(
            text.encode("utf-8")
        ).hexdigest()

    except Exception as e:
        print(f"ページ取得エラー ({url})")
        print(e)
        return None


# =========================
# イベント登録
# =========================

def bind_events(c: discord.Client):

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def check_sites():

        try:

            channel = c.get_channel(CHANNEL_ID)

            if not channel:
                print("チャンネルが見つかりません")
                return

            for site in MONITORED_SITES:

                try:

                    current_hash = get_page_hash(
                        site["url"]
                    )

                    if current_hash is None:
                        continue

                    # 初回
                    if site.get("last_hash") is None:

                        site["last_hash"] = current_hash

                        print(
                            f"初回チェック完了: {site['name']}"
                        )

                        continue

                    # 更新検知
                    if current_hash != site["last_hash"]:

                        print(
                            f"更新検知: {site['name']}"
                        )

                        site["last_hash"] = current_hash

                        notification = (
                            f"{site.get('mention', '@everyone')}\n"
                            f"{site.get('message', '更新を検知しました')}\n"
                            f"{site['url']}"
                        )

                        await channel.send(notification)

                except Exception as e:

                    print(
                        f"監視エラー ({site.get('name', 'unknown')})"
                    )

                    traceback.print_exc()

        except Exception as e:

            print("check_sites 全体エラー")
            traceback.print_exc()

    async def watchdog():

        await c.wait_until_ready()

        while not c.is_closed():

            try:

                if not check_sites.is_running():

                    print(
                        "check_sites が停止していたため再起動します"
                    )

                    check_sites.start()

            except Exception:
                traceback.print_exc()

            await asyncio.sleep(30)

    @c.event
    async def on_ready():

        print(f"{c.user} としてログインしました")

        print(
            f"監視サイト数: {len(MONITORED_SITES)}"
        )

        print(
            f"チェック間隔: {CHECK_INTERVAL}秒"
        )

        for site in MONITORED_SITES:

            print(
                f" - {site['name']}: {site['url']}"
            )

        if not check_sites.is_running():
            check_sites.start()

        c.loop.create_task(watchdog())

    @c.event
    async def on_message(message):

        if message.author == c.user:
            return

        # =========================
        # !status
        # =========================

        if message.content == "!status":

            status_msg = (
                "**📊 現在の監視状況:**\n"
            )

            for i, site in enumerate(
                MONITORED_SITES,
                1
            ):

                status = (
                    "✅ 監視中"
                    if site.get("last_hash")
                    else "⏳ 初期化中"
                )

                status_msg += (
                    f"{i}. {site['name']}: {status}\n"
                )

            status_msg += (
                f"\nチェック間隔: "
                f"{CHECK_INTERVAL}秒"
            )

            await message.reply(status_msg)

        # =========================
        # !check
        # =========================

        elif message.content == "!check":

            await message.reply(
                "🔍 手動チェックを開始します..."
            )

            await check_sites()

            await message.reply(
                "✅ チェック完了しました。"
            )

        # =========================
        # !commands
        # =========================

        elif message.content == "!commands":

            commands_msg = (
                "**🤖 Bot コマンド一覧:**\n"
                "`!status` - 現在の監視状況\n"
                "`!check` - 手動チェック\n"
                "`!commands` - コマンド一覧\n"
                "`!help` - ヘルプ\n"
                "`!kutabare` - ぐえ～\n"
                "`!roll NdM` - ダイス"
            )

            await message.reply(commands_msg)

        elif message.content == "!help":

            await message.reply("たすけて～")

        elif message.content == "!kutabare":

            await message.reply("ぐえ～")

        # =========================
        # ダイス
        # =========================

        elif message.content.startswith("!roll"):

            content = (
                message.content[len("!roll"):].strip()
            )

            m = re.match(
                r"^(\d+)\s*d\s*(\d+)$",
                content
            )

            if not m:

                await message.reply(
                    "使い方: `!roll NdM`"
                )

                return

            n = int(m.group(1))
            sides = int(m.group(2))

            if n <= 0 or sides <= 0:

                await message.reply(
                    "正の整数を指定してください"
                )

                return

            if n > 100:

                await message.reply(
                    "最大100個まで"
                )

                return

            rolls = [
                random.randint(1, sides)
                for _ in range(n)
            ]

            total = sum(rolls)

            if n == 1:

                await message.reply(
                    f"🎲 出目: {rolls[0]}"
                )

            else:

                rolls_str = ", ".join(
                    map(str, rolls)
                )

                await message.reply(
                    f"🎲 出目: [{rolls_str}]\n"
                    f"合計: {total}"
                )


# =========================
# 起動
# =========================

async def start_bot():

    global client

    if not DISCORD_TOKEN:

        raise RuntimeError(
            "DISCORD_TOKEN is not set"
        )

    client = create_client()

    bind_events(client)

    await client.start(DISCORD_TOKEN)


if __name__ == "__main__":

    asyncio.run(start_bot())