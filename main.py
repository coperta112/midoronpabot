import discord
from discord.ext import tasks

import os
import re
import random
import asyncio
import json
import traceback

import feedparser

from dotenv import load_dotenv

load_dotenv()

# =========================
# 環境変数
# =========================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

CHANNEL_ID = int(
    os.getenv("CHANNEL_ID", 0)
)

CHECK_INTERVAL = int(
    os.getenv("CHECK_INTERVAL", 300)
)

MONITORED_SITES_JSON = os.getenv(
    "MONITORED_SITES",
    "[]"
)

try:

    MONITORED_SITES = json.loads(
        MONITORED_SITES_JSON
    )

except Exception as e:

    print("MONITORED_SITES 読み込み失敗")

    print(e)

    MONITORED_SITES = []

client: discord.Client | None = None


# =========================
# Discord Client
# =========================

def create_client() -> discord.Client:

    intents = discord.Intents.default()

    intents.message_content = True

    return discord.Client(
        intents=intents
    )


# =========================
# RSS取得
# =========================

def get_latest_feed(feed_url):

    try:

        feed = feedparser.parse(feed_url)

        if not feed.entries:

            return None

        entry = feed.entries[0]

        return {
            "id": entry.get(
                "id",
                entry.get("link")
            ),

            "title": entry.get(
                "title",
                "No Title"
            ),

            "link": entry.get(
                "link",
                ""
            ),

            "published": entry.get(
                "published",
                "日時不明"
            )
        }

    except Exception as e:

        print(
            f"RSS取得エラー: {feed_url}"
        )

        print(e)

        return None


# =========================
# イベント登録
# =========================

def bind_events(c: discord.Client):

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def check_sites():

        try:

            channel = c.get_channel(
                CHANNEL_ID
            )

            if not channel:

                print(
                    "チャンネルが見つかりません"
                )

                return

            for site in MONITORED_SITES:

                try:

                    latest = get_latest_feed(
                        site["url"]
                    )

                    if latest is None:
                        continue

                    latest_id = latest["id"]

                    latest_title = latest["title"]

                    latest_link = latest["link"]

                    latest_published = (
                        latest["published"]
                    )

                    # =========================
                    # 初回
                    # =========================

                    if site.get("last_id") is None:

                        site["last_id"] = latest_id

                        print(
                            f"初回チェック完了: "
                            f"{site['name']}"
                        )

                        continue

                    # =========================
                    # 更新検知
                    # =========================

                    if latest_id != site["last_id"]:

                        print(
                            f"更新検知: "
                            f"{site['name']}"
                        )

                        site["last_id"] = latest_id

                        notification = (
                            f"{site.get('mention', '@everyone')}\n\n"
                            f"📄 **{latest_title}** "
                            f"が更新されました\n\n"
                            f"🕒 更新日時: "
                            f"{latest_published}\n"
                            f"🔗 {latest_link}"
                        )

                        await channel.send(
                            notification
                        )

                except Exception:

                    print(
                        f"監視エラー: "
                        f"{site.get('name')}"
                    )

                    traceback.print_exc()

        except Exception:

            print(
                "check_sites 全体エラー"
            )

            traceback.print_exc()

    @c.event
    async def on_ready():

        print(
            f"{c.user} としてログインしました"
        )

        print(
            f"監視サイト数: "
            f"{len(MONITORED_SITES)}"
        )

        print(
            f"チェック間隔: "
            f"{CHECK_INTERVAL}秒"
        )

        for site in MONITORED_SITES:

            print(
                f" - {site['name']}: "
                f"{site['url']}"
            )

        if not check_sites.is_running():

            check_sites.start()

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
                    if site.get("last_id")
                    else "⏳ 初期化中"
                )

                status_msg += (
                    f"{i}. "
                    f"{site['name']}: "
                    f"{status}\n"
                )

            status_msg += (
                f"\nチェック間隔: "
                f"{CHECK_INTERVAL}秒"
            )

            await message.reply(
                status_msg
            )

        # =========================
        # !check
        # =========================

        elif message.content == "!check":

            await message.reply(
                "🔍 手動チェック中..."
            )

            await check_sites()

            await message.reply(
                "✅ チェック完了"
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

    await client.start(
        DISCORD_TOKEN
    )


if __name__ == "__main__":

    asyncio.run(start_bot())