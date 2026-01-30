from flask import Flask
import threading
import os
import asyncio
import time
import traceback
import signal
import sys

import discord  # 例外クラス参照用
import main

app = Flask(__name__)

# Bot起動状態を管理
bot_running = False
last_error = ""
start_time = time.time()

MAX_RETRIES = 3
RETRY_DELAY = 300  # 5分（429時などの待機）

@app.route("/")
def home():
    status = "running" if bot_running else "starting"
    return f"Bot is {status}!", 200

@app.route("/health")
def health():
    """Renderのヘルスチェック用"""
    if bot_running:
        return "OK", 200
    return "Starting", 503

@app.route("/status")
def status():
    """詳細ステータス"""
    client = getattr(main, "client", None)
    return {
        "bot_running": bot_running,
        "bot_user": str(client.user) if (client and client.user) else "Not logged in",
        "monitored_sites": len(getattr(main, "MONITORED_SITES", [])),
        "uptime_sec": int(time.time() - start_time),
        "last_error": last_error,
    }, 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)

async def run_discord_with_retries():
    """Discord bot をメインスレッド（asyncio）で起動。例外に応じてリトライする。"""
    global bot_running, last_error

    if not main.DISCORD_TOKEN:
        last_error = "DISCORD_TOKEN is not set"
        bot_running = False
        print("エラー: DISCORD_TOKENが設定されていません！")
        return

    if main.CHANNEL_ID == 0:
        print("警告: CHANNEL_IDが設定されていません（0のまま）")

    retry_count = 0

    while retry_count < MAX_RETRIES:
        try:
            print("=" * 50)
            print(f"Discord Botを起動しています... (試行 {retry_count + 1}/{MAX_RETRIES})")
            print(f"DISCORD_TOKEN設定: {'あり' if main.DISCORD_TOKEN else 'なし'}")
            print(f"CHANNEL_ID: {main.CHANNEL_ID}")
            print(f"監視サイト数: {len(main.MONITORED_SITES)}")
            print("=" * 50)

            # ★2回目以降は前回セッションを確実に捨てる（Session is closed 対策）
            if retry_count > 0:
                try:
                    await main.reset_client()
                except Exception:
                    pass

            bot_running = True
            last_error = ""

            await main.start_bot()

            # 通常ここには来ない（切断などで start_bot が戻った場合）
            bot_running = False
            last_error = "Discord client stopped unexpectedly"
            return

        except discord.errors.HTTPException as e:
            bot_running = False
            last_error = f"HTTPException: status={getattr(e, 'status', None)} {e}"
            if getattr(e, "status", None) == 429:
                retry_count += 1
                wait_time = RETRY_DELAY * retry_count
                print("=" * 50)
                print(f"⚠️ レート制限エラー (試行 {retry_count}/{MAX_RETRIES})")
                print("Discord側で一時的にブロックされています")
                print(f"{wait_time}秒後に再試行します...")
                print("=" * 50)
                await asyncio.sleep(wait_time)
                continue
            else:
                print(f"Discord HTTPエラー: {e}")
                traceback.print_exc()
                return

        except discord.LoginFailure as e:
            bot_running = False
            last_error = f"LoginFailure: {e}"
            print("ログイン失敗: DISCORD_TOKENが正しいか確認してください")
            traceback.print_exc()
            return

        except Exception as e:
            bot_running = False
            last_error = f"Exception: {e}"
            print(f"Bot起動エラー: {e}")
            traceback.print_exc()
            return

def signal_handler(sig, frame):
    print("シャットダウンシグナルを受信しました")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("=" * 50)
    print("Discord Bot with Flask (Render/Koyeb用)")
    print("=" * 50)

    # Flaskは別スレッド
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    print("Flaskサーバーを起動しました")

    # Discordはメインスレッド（重要）
    asyncio.run(run_discord_with_retries())
