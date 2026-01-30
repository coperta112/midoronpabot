from flask import Flask
import threading
import os
import asyncio
import time
import traceback
import signal
import sys

import discord  # 429など例外クラス参照用

import main  # main.start_bot() を呼ぶ想定（後述）

app = Flask(__name__)

# Bot起動状態を管理
bot_running = False
last_error = None
start_time = time.time()

MAX_RETRIES = 3
RETRY_DELAY = 300  # 5分（429時などの待機）

@app.route("/")
def home():
    status = "running" if bot_running else "starting"
    return f"Bot is {status}!", 200

@app.route("/health")
def health():
    # Render/Koyebのヘルスチェック用
    if bot_running:
        return "OK", 200
    return "Starting", 503

@app.route("/status")
def status():
    client = getattr(main, "client", None)
    return {
        "bot_running": bot_running,
        "bot_user": str(client.user) if (client and client.user) else "Not logged in",
        "monitored_sites": len(getattr(main, "MONITORED_SITES", [])),
        "uptime_sec": int(time.time() - start_time),
        "last_error": last_error or "",
    }, 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)

async def run_discord_with_retries():
    """
    Discord bot をメインスレッド（asyncio）で起動。
    例外に応じてリトライする。
    """
    global bot_running, last_error

    # 設定チェック
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

            bot_running = True
            last_error = None

            # ★重要: main.start_bot() は内部で client を作成し、await client.start(token) する想定
            await main.start_bot()

            # start_bot() が正常終了することは通常ない（切断時などに戻る）
            bot_running = False
            last_error = "Discord client stopped unexpectedly"
            return

        except discord.errors.HTTPException as e:
            bot_running = False
            last_error = f"HTTPException: status={getattr(e, 'status', None)} {e}"
            # 429（レート制限）だけは待って再試行
            if getattr(e, "status", None) == 429:
                retry_count += 1
                wait_time = RETRY_DELAY * retry_count
                print("=" * 50)
                print(f"⚠️ レート制限エラー (試行 {retry_count}/{MAX_RETRIES})")
                print(f"{wait_time}秒後に再試行します...")
                print("=" * 50)
                await asyncio.sleep(wait_time)
                continue
            else:
                print(f"Discord HTTPエラー: {e}")
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
    # ここで無理に close までやるとループ都合で面倒なので、プロセス終了でOKにする
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
