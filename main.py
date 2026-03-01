import discord
from discord.ext import tasks
import requests
from bs4 import BeautifulSoup
import hashlib
import difflib
import os
import json
import traceback
import re
import random
import time
import asyncio
from dotenv import load_dotenv
load_dotenv()

# 環境変数から設定を取得
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))
SHOW_DIFF = os.getenv("SHOW_DIFF", "True").lower() == "true"

# MONITORED_SITESを環境変数から取得（JSON形式）
MONITORED_SITES_JSON = os.getenv("MONITORED_SITES", "[]")
try:
    MONITORED_SITES = json.loads(MONITORED_SITES_JSON)
except json.JSONDecodeError:
    print("警告: MONITORED_SITESの解析に失敗しました。空のリストを使用します。")
    MONITORED_SITES = []

# ローカル環境のフォールバック（app.pyからimportされる想定なのでexitしない）
if not DISCORD_TOKEN or CHANNEL_ID == 0:
    try:
        from config import DISCORD_TOKEN, CHANNEL_ID, CHECK_INTERVAL, SHOW_DIFF, MONITORED_SITES
        print("ローカルのconfig.pyから設定を読み込みました")
    except ImportError:
        print("エラー: 環境変数またはconfig.pyが必要です")

# ------------------------------------------------------------
# 重要: import時にClientを作らない
# app.pyの/statusから参照できるように client はグローバル保持
# ------------------------------------------------------------
client: discord.Client | None = None

def create_client() -> discord.Client:
    intents = discord.Intents.default()
    intents.message_content = True  # on_messageでコマンド読むなら必須（Portal側でもON必要）
    return discord.Client(intents=intents)

def get_page_content(url, selector=None, cache_bust=True, timeout=10):
    """ウェブページのコンテンツを取得し、(content, etag, last_modified) を返す。"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
            "Cache-Control": "no-cache",
        }
        req_url = url
        if cache_bust:
            sep = "&" if "?" in url else "?"
            req_url = f"{url}{sep}_={int(time.time())}"

        response = requests.get(req_url, headers=headers, timeout=timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        if selector:
            element = soup.select_one(selector)
            if element:
                content = element.get_text(separator="\n", strip=True)
            else:
                print(f"警告: セレクタ '{selector}' が見つかりません")
                content = soup.get_text(separator="\n", strip=True)
        else:
            content = soup.get_text(separator="\n", strip=True)

        lines = [line.strip() for line in content.split("\n") if line.strip()]
        etag = response.headers.get("ETag")
        last_mod = response.headers.get("Last-Modified")
        return "\n".join(lines), etag, last_mod

    except Exception as e:
        print(f"エラー ({url}): {e}")
        traceback.print_exc()
        return None, None, None

def get_content_hash(content, etag=None, last_mod=None):
    if content is None:
        return None
    base = content
    if etag:
        base += f"\nETag:{etag}"
    if last_mod:
        base += f"\nLast-Modified:{last_mod}"
    return hashlib.md5(base.encode()).hexdigest()

def get_diff(old_content, new_content, max_lines=20):
    if not old_content or not new_content:
        return None

    old_lines = old_content.split("\n")
    new_lines = new_content.split("\n")

    diff = list(difflib.unified_diff(
        old_lines,
        new_lines,
        lineterm="",
        n=0
    ))

    if len(diff) <= 2:
        return None

    added = []
    removed = []

    for line in diff[2:]:
        if line.startswith("+"):
            added.append(line[1:])
        elif line.startswith("-"):
            removed.append(line[1:])

    diff_msg = ""

    if removed:
        diff_msg += "**🗑️ 削除された内容:**\n"
        for line in removed[:max_lines]:
            if len(line) > 100:
                line = line[:100] + "..."
            diff_msg += f"- {line}\n"
        if len(removed) > max_lines:
            diff_msg += f"... 他 {len(removed) - max_lines} 行\n"
        diff_msg += "\n"

    if added:
        diff_msg += "**✨ 追加された内容:**\n"
        for line in added[:max_lines]:
            if len(line) > 100:
                line = line[:100] + "..."
            diff_msg += f"+ {line}\n"
        if len(added) > max_lines:
            diff_msg += f"... 他 {len(added) - max_lines} 行\n"

    return diff_msg if diff_msg else None

def bind_events(c: discord.Client):
    """Clientにイベント/タスクを紐付ける"""

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def check_websites():
        try:
            channel = c.get_channel(CHANNEL_ID)
            if not channel:
                print("チャンネルが見つかりません（CHANNEL_IDが正しいか、Botがそのサーバーにいるか確認）")
                return

            for site in MONITORED_SITES:
                try:
                    current_content, etag, last_mod = get_page_content(site["url"], site.get("selector"))
                    if current_content is None:
                        continue

                    current_hash = get_content_hash(current_content, etag, last_mod)

                    # 初回実行時
                    if "hash" not in site or site["hash"] is None:
                        site["hash"] = current_hash
                        site["content"] = current_content
                        site["etag"] = etag
                        site["last_modified"] = last_mod
                        print(f"初回チェック完了: {site.get('name', '(no name)')}")
                        continue

                    # 更新を検知
                    if current_hash != site.get("hash"):
                        print(f"更新を検知: {site.get('name', '(no name)')}")

                        diff_msg = None
                        if SHOW_DIFF and site.get("content"):
                            diff_msg = get_diff(site.get("content"), current_content)

                        site["hash"] = current_hash
                        site["content"] = current_content
                        site["etag"] = etag
                        site["last_modified"] = last_mod

                        notification = f"{site.get('mention', '@everyone')}\n{site.get('message', '(no message)')}\n{site.get('url', '')}"

                        if diff_msg:
                            notification += f"\n\n{diff_msg}"

                        # Discordのメッセージ長制限（2000文字）を考慮
                        if len(notification) > 2000:
                            notification = notification[:1900] + "\n\n... (差分が長すぎるため省略されました)"

                        try:
                            await channel.send(notification)
                        except Exception:
                            print("通知送信でエラーが発生しました")
                            traceback.print_exc()

                except Exception as e:
                    print(f"サイトチェック中にエラー ({site.get('url')}): {e}")
                    traceback.print_exc()
                    # サイト単位のエラーは無視して次へ
                    continue

        except Exception as e:
            print(f"check_websites 全体でエラー: {e}")
            traceback.print_exc()
            # 例外を外へ出さずにループ継続させる
            return

    async def _ensure_check_websites_running():
        await c.wait_until_ready()
        while not c.is_closed():
            try:
                if not check_websites.is_running():
                    try:
                        check_websites.start()
                        print("check_websites を再起動しました")
                    except RuntimeError:
                        # 既に開始済みの競合などは無視
                        pass
            except Exception as e:
                print(f"ウォッチドッグでエラー: {e}")
                traceback.print_exc()
            await asyncio.sleep(10)

    @c.event
    async def on_ready():
        print(f"{c.user} としてログインしました")
        print(f"監視中のサイト: {len(MONITORED_SITES)}件")
        print(f"チェック間隔: {CHECK_INTERVAL}秒")
        print(f"差分表示: {'有効' if SHOW_DIFF else '無効'}")
        for site in MONITORED_SITES:
            print(f"  - {site.get('name','(no name)')}: {site.get('url','')}")

        # 二重 start 防止
        if not check_websites.is_running():
            check_websites.start()
        # ウォッチドッグ起動
        try:
            c.loop.create_task(_ensure_check_websites_running())
        except Exception:
            pass

    @c.event
    async def on_message(message):
        if message.author == c.user:
            return

        if message.content == "!status":
            status_msg = "**📊 現在の監視状況:**\n"
            for i, site in enumerate(MONITORED_SITES, 1):
                status = "✅ 監視中" if site.get("hash") else "⏳ 初期化中"
                status_msg += f"{i}. {site.get('name','(no name)')}: {status}\n"
            status_msg += f"\nチェック間隔: {CHECK_INTERVAL}秒"
            await message.channel.send(status_msg)

        elif message.content == "!check":
            await message.channel.send("🔍 手動チェックを開始します...")
            await check_websites()
            await message.channel.send("✅ チェック完了しました。")

        elif message.content == "!commands":
            commands_msg = (
                "**🤖 Bot コマンド一覧:**\n"
                "`!status` - 現在の監視状況を表示\n"
                "`!check` - 手動で即座にチェックを実行\n"
                "`!commands` - このコマンド一覧を表示\n"
                "`!help` - ヘルプメッセージを表示"
            )
            await message.channel.send(commands_msg)

        elif message.content == "!help":
            await message.channel.send("たすけて～")
        
        # !roll コマンド: 形式は "!roll <N>d<M>" または "!roll <N> d <M>" を許容
        # 例: !roll 3d6, !roll 2 d 20
        elif message.content.startswith("!roll"):
            content = message.content[len("!roll"):].strip()
            m = re.match(r"^(\d+)\s*d\s*(\d+)$", content)
            if not m:
                await message.channel.send("使い方: `!roll NdM` 例: `!roll 1d100` あるいは `!roll 1 d 100`")
                return

            try:
                n = int(m.group(1))
                sides = int(m.group(2))
            except Exception:
                await message.channel.send("数値の解析に失敗しました。正しい形式で指定してください。")
                return

            # 安全策: 回数・面数に上限を設ける
            if n <= 0 or sides <= 0:
                await message.channel.send("回数と面数は正の整数で指定してください。")
                return
            if n > 100:
                await message.channel.send("過度な回数です。最大100個まで指定できます。")
                return
            if sides > 1000000:
                await message.channel.send("過度な面数です。面数は最大1,000,000まで指定できます。")
                return

            rolls = [random.randint(1, sides) for _ in range(n)]
            total = sum(rolls)
            # 結果表示: 個別の出目と合計
            if n == 1:
                await message.channel.send(f"🎲 出目: {rolls[0]}")
            else:
                # 出力が長くなりすぎないように制限
                rolls_str = ", ".join(str(r) for r in rolls)
                if len(rolls_str) > 1500:
                    rolls_str = rolls_str[:1500] + "..."
                await message.channel.send(f"🎲 出目: [{rolls_str}]\n合計: {total}")

async def reset_client():
    """既存 client を閉じて破棄する（リトライ時に新規clientへ差し替えるため）"""
    global client
    if client is not None:
        try:
            await client.close()
        except Exception:
            pass
    client = None

async def start_bot():
    """
    app.py から呼ばれる起動関数。
    429後の再試行などで Session is closed を避けるため、毎回 client を作り直す。
    """
    global client

    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set")

    # ★毎回作り直す：セッションが閉じている状態の再利用を避ける
    client = create_client()
    bind_events(client)

    await client.start(DISCORD_TOKEN)

# ローカルデバッグ用（任意）
if __name__ == "__main__":
    import asyncio
    asyncio.run(start_bot())
