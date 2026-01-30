# main.py
import discord
from discord.ext import tasks
import requests
from bs4 import BeautifulSoup
import hashlib
import difflib
import os
import json

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID', 0))
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', 300))
SHOW_DIFF = os.getenv('SHOW_DIFF', 'True').lower() == 'true'

MONITORED_SITES_JSON = os.getenv('MONITORED_SITES', '[]')
try:
    MONITORED_SITES = json.loads(MONITORED_SITES_JSON)
except json.JSONDecodeError:
    print("警告: MONITORED_SITESの解析に失敗しました。空のリストを使用します。")
    MONITORED_SITES = []

client = None  # ★ import時は作らない

def create_client():
    intents = discord.Intents.default()
    intents.message_content = True
    return discord.Client(intents=intents)

def get_page_content(url, selector=None):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        if selector:
            element = soup.select_one(selector)
            content = element.get_text(separator='\n', strip=True) if element else soup.get_text(separator='\n', strip=True)
        else:
            content = soup.get_text(separator='\n', strip=True)
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        return '\n'.join(lines)
    except Exception as e:
        print(f"エラー ({url}): {e}")
        return None

def get_content_hash(content):
    if content is None:
        return None
    return hashlib.md5(content.encode()).hexdigest()

def get_diff(old_content, new_content, max_lines=20):
    if not old_content or not new_content:
        return None
    old_lines = old_content.split('\n')
    new_lines = new_content.split('\n')
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm='', n=0))
    if len(diff) <= 2:
        return None
    added, removed = [], []
    for line in diff[2:]:
        if line.startswith('+'):
            added.append(line[1:])
        elif line.startswith('-'):
            removed.append(line[1:])
    diff_msg = ""
    if removed:
        diff_msg += "**🗑️ 削除された内容:**\n"
        for line in removed[:max_lines]:
            diff_msg += f"- {(line[:100] + '...') if len(line) > 100 else line}\n"
        if len(removed) > max_lines:
            diff_msg += f"... 他 {len(removed) - max_lines} 行\n"
        diff_msg += "\n"
    if added:
        diff_msg += "**✨ 追加された内容:**\n"
        for line in added[:max_lines]:
            diff_msg += f"+ {(line[:100] + '...') if len(line) > 100 else line}\n"
        if len(added) > max_lines:
            diff_msg += f"... 他 {len(added) - max_lines} 行\n"
    return diff_msg if diff_msg else None

def bind_events(c: discord.Client):
    @tasks.loop(seconds=CHECK_INTERVAL)
    async def check_websites():
        channel = c.get_channel(CHANNEL_ID)
        if not channel:
            print("チャンネルが見つかりません")
            return

        for site in MONITORED_SITES:
            current_content = get_page_content(site['url'], site.get('selector'))
            if current_content is None:
                continue
            current_hash = get_content_hash(current_content)

            if 'hash' not in site or site['hash'] is None:
                site['hash'] = current_hash
                site['content'] = current_content
                print(f"初回チェック完了: {site['name']}")
                continue

            if current_hash != site['hash']:
                print(f"更新を検知: {site['name']}")
                diff_msg = get_diff(site.get('content'), current_content) if SHOW_DIFF else None
                site['hash'] = current_hash
                site['content'] = current_content

                notification = f"{site.get('mention', '@everyone')}\n{site['message']}\n{site['url']}"
                if diff_msg:
                    notification += f"\n\n{diff_msg}"
                if len(notification) > 2000:
                    notification = notification[:1900] + "\n\n... (差分が長すぎるため省略されました)"
                await channel.send(notification)

    @c.event
    async def on_ready():
        print(f'{c.user} としてログインしました')
        print(f"監視中のサイト: {len(MONITORED_SITES)}件")
        check_websites.start()

    @c.event
    async def on_message(message):
        if message.author == c.user:
            return
        if message.content == '!status':
            status_msg = "**📊 現在の監視状況:**\n"
            for i, site in enumerate(MONITORED_SITES, 1):
                status = "✅ 監視中" if site.get('hash') else "⏳ 初期化中"
                status_msg += f"{i}. {site['name']}: {status}\n"
            status_msg += f"\nチェック間隔: {CHECK_INTERVAL}秒"
            await message.channel.send(status_msg)

        elif message.content == '!check':
            await message.channel.send("🔍 手動チェックを開始します...")
            await check_websites()
            await message.channel.send("✅ チェック完了しました。")

        elif message.content == '!help':
            await message.channel.send("たすけて～")

    return check_websites

async def start_bot():
    global client
    client = create_client()
    bind_events(client)
    await client.start(DISCORD_TOKEN)
