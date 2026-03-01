import discord
from discord.ext import tasks
import requests
import xml.etree.ElementTree as ET
import os
import json
import traceback
import re
import random
import asyncio
import time

from dotenv import load_dotenv
load_dotenv()

# 環境変数から設定を取得
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))

# ローカル環境のフォールバック
if not DISCORD_TOKEN or CHANNEL_ID == 0:
    try:
        from config import DISCORD_TOKEN, CHANNEL_ID, CHECK_INTERVAL
        print("ローカルのconfig.pyから設定を読み込みました")
    except ImportError:
        print("エラー: 環境変数またはconfig.pyが必要です")

# 監視するRSSフィードの設定
MONITORED_FEEDS = [
    {
        "name": "Wiki更新",
        "rss_url": "https://rss.app/feeds/HlEeXotxtnT77OpD.xml",
        "mention": "@everyone",
        "message": "📄 Wikiが更新されました！",
        "last_item_id": None,
    },
    {
        "name": "パッチノート更新",
        "rss_url": "https://rss.app/feeds/2oBXDFVTCEGEFsRm.xml",
        "mention": "@everyone",
        "message": "🔧 パッチノートが更新されました！",
        "last_item_id": None,
    },
]

client: discord.Client | None = None

def create_client() -> discord.Client:
    intents = discord.Intents.default()
    intents.message_content = True
    return discord.Client(intents=intents)

def get_latest_rss_item(rss_url):
    """RSSフィードから最新のアイテムを取得する"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml",
        }
        response = requests.get(rss_url, headers=headers, timeout=15)
        response.raise_for_status()

        root = ET.fromstring(response.content)

        # RSSの名前空間を処理
        ns = {}
        channel = root.find("channel")
        if channel is None:
            return None

        item = channel.find("item")
        if item is None:
            return None

        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        pub_date = item.findtext("pubDate", "").strip()
        guid = item.findtext("guid", link).strip()

        return {
            "id": guid or link,
            "title": title,
            "link": link,
            "pub_date": pub_date,
        }

    except Exception as e:
        print(f"RSSフィード取得エラー ({rss_url}): {e}")
        traceback.print_exc()
        return None

def bind_events(c: discord.Client):
    @tasks.loop(seconds=CHECK_INTERVAL)
    async def check_feeds():
        try:
            channel = c.get_channel(CHANNEL_ID)
            if not channel:
                print("チャンネルが見つかりません")
                return

            for feed in MONITORED_FEEDS:
                try:
                    item = get_latest_rss_item(feed["rss_url"])
                    if item is None:
                        continue

                    # 初回実行時はIDだけ記録して通知しない
                    if feed["last_item_id"] is None:
                        feed["last_item_id"] = item["id"]
                        print(f"初回チェック完了: {feed['name']} / 最新: {item['title']}")
                        continue

                    # 新しいアイテムが来たら通知
                    if item["id"] != feed["last_item_id"]:
                        print(f"更新を検知: {feed['name']} / {item['title']}")
                        feed["last_item_id"] = item["id"]

                        notification = (
                            f"{feed['mention']}\n"
                            f"{feed['message']}\n"
                            f"**{item['title']}**\n"
                            f"{item['link']}"
                        )

                        await message.reply(notification)

                except Exception as e:
                    print(f"フィードチェック中にエラー ({feed['name']}): {e}")
                    traceback.print_exc()
                    continue

        except Exception as e:
            print(f"check_feeds 全体でエラー: {e}")
            traceback.print_exc()

    async def _watchdog():
        await c.wait_until_ready()
        while not c.is_closed():
            try:
                if not check_feeds.is_running():
                    check_feeds.start()
                    print("check_feeds を再起動しました")
            except Exception as e:
                print(f"ウォッチドッグでエラー: {e}")
            await asyncio.sleep(10)

    @c.event
    async def on_ready():
        print(f"{c.user} としてログインしました")
        print(f"監視中のRSSフィード: {len(MONITORED_FEEDS)}件")
        print(f"チェック間隔: {CHECK_INTERVAL}秒")
        for feed in MONITORED_FEEDS:
            print(f"  - {feed['name']}: {feed['rss_url']}")

        if not check_feeds.is_running():
            check_feeds.start()
        try:
            c.loop.create_task(_watchdog())
        except Exception:
            pass

    @c.event
    async def on_message(message):
        if message.author == c.user:
            return

        if message.content == "!status":
            status_msg = "**📊 現在の監視状況:**\n"
            for i, feed in enumerate(MONITORED_FEEDS, 1):
                status = "✅ 監視中" if feed["last_item_id"] else "⏳ 初期化中"
                status_msg += f"{i}. {feed['name']}: {status}\n"
            status_msg += f"\nチェック間隔: {CHECK_INTERVAL}秒"
            await message.reply(status_msg)

        elif message.content == "!check":
            await message.reply("🔍 手動チェックを開始します...")
            await check_feeds()
            await message.reply("✅ チェック完了しました。")

        elif message.content == "!commands":
            commands_msg = (
                "**🤖 Bot コマンド一覧:**\n"
                "`!status` - 現在の監視状況を表示\n"
                "`!check` - 手動で即座にチェックを実行\n"
                "`!commands` - このコマンド一覧を表示\n"
                "`!help` - ヘルプメッセージを表示\n"
                "`!roll NdM` - ダイスロール (例: `!roll 2d6`)"
            )
            await message.reply(commands_msg)

        elif message.content == "!help":
            await message.reply("たすけて～")

        elif message.content.startswith("!roll"):
            content = message.content[len("!roll"):].strip()
            m = re.match(r"^(\d+)\s*d\s*(\d+)$", content)
            if not m:
                await message.reply("使い方: `!roll NdM` 例: `!roll 1d100`")
                return

            try:
                n = int(m.group(1))
                sides = int(m.group(2))
            except Exception:
                await message.reply("数値の解析に失敗しました。")
                return

            if n <= 0 or sides <= 0:
                await message.reply("回数と面数は正の整数で指定してください。")
                return
            if n > 100:
                await message.reply("最大100個まで指定できます。")
                return
            if sides > 1000000:
                await message.reply("面数は最大1,000,000まで指定できます。")
                return

            rolls = [random.randint(1, sides) for _ in range(n)]
            total = sum(rolls)
            if n == 1:
                await message.reply(f"🎲 出目: {rolls[0]}")
            else:
                rolls_str = ", ".join(str(r) for r in rolls)
                if len(rolls_str) > 1500:
                    rolls_str = rolls_str[:1500] + "..."
                await message.reply(f"🎲 出目: [{rolls_str}]\n合計: {total}")

async def reset_client():
    global client
    if client is not None:
        try:
            await client.close()
        except Exception:
            pass
    client = None

async def start_bot():
    global client

    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set")

    client = create_client()
    bind_events(client)

    await client.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(start_bot())