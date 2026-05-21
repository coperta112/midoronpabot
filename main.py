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

        # feedparserのエラー確認
        if feed.bozo:
            print(
                f"RSS解析警告: {feed.bozo_exception}"
            )

        if not feed.entries:

            print(
                f"RSSエントリなし: {feed_url}"
            )

            return None

        entry = feed.entries[0]

        return {
            "id": entry.get(
                "id",
                entry.get("link", "")
            ),

            "title": entry.get(
                "title",
                "No Title"
            ),

            "link": entry.get(
                "link",
                feed_url
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

        traceback.print_exc()

        return None


# =========================
# イベント登録
# =========================

def bind_events(c: discord.Client):

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def check_sites():

        print("RSSチェック開始")

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

                    print(
                        f"チェック中: "
                        f"{site['name']}"
                    )

                    latest = get_latest_feed(
                        site["url"]
                    )

                    if latest is None:

                        print(
                            f"RSS取得失敗: "
                            f"{site['name']}"
                        )

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
                            f"📄 **{latest_title}** が更新されました\n\n"
                            f"🕒 更新日時: {latest_published}\n"
                            f"🔗 {latest_link}"
                        )

                        await channel.send(
                            notification
                        )

                    else:

                        print(
                            f"更新なし: "
                            f"{site['name']}"
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

        # 初回即時実行
        await check_sites()

        # ループ開始
        if not check_sites.is_running():

            check_sites.start()

            print(
                "check_sites 開始"
            )

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

            await message.reply(
                commands_msg
            )

        elif message.content == "!help":

            await message.reply(
                "たすけて～"
            )

        elif message.content == "!kutabare":

            await message.reply(
                "ぐえ～"
            )

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

    await client.start(
        DISCORD_TOKEN
    )


# =========================
# systemd対策
# =========================

def run():

    asyncio.run(
        start_bot()
    )


if __name__ == "__main__":

    run()