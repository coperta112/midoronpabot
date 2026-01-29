from flask import Flask
import threading
import os
import signal
import sys
import time
import discord

app = Flask(__name__)

# Bot起動状態を管理
bot_running = False
bot_thread = None
retry_count = 0
MAX_RETRIES = 3
RETRY_DELAY = 300  # 5分

# main.pyから設定を読み込む
import main

@app.route('/')
def home():
    status = "running" if bot_running else "starting"
    return f"Bot is {status}!", 200

@app.route('/health')
def health():
    """Renderのヘルスチェック用"""
    if bot_running:
        return "OK", 200
    else:
        return "Starting", 503

@app.route('/status')
def status():
    """詳細ステータス"""
    client = main.client
    return {
        "bot_running": bot_running,
        "bot_user": str(client.user) if client.user else "Not logged in",
        "monitored_sites": len(main.MONITORED_SITES)
    }, 200

def run_bot():
    """別スレッドでDiscord botを起動（リトライ機能付き）"""
    global bot_running, retry_count
    
    while retry_count < MAX_RETRIES:
        try:
            print("=" * 50)
            print(f"Discord Botを起動しています... (試行 {retry_count + 1}/{MAX_RETRIES})")
            print(f"DISCORD_TOKEN設定: {'あり' if main.DISCORD_TOKEN else 'なし'}")
            print(f"CHANNEL_ID: {main.CHANNEL_ID}")
            print(f"監視サイト数: {len(main.MONITORED_SITES)}")
            print("=" * 50)
            
            if not main.DISCORD_TOKEN:
                print("エラー: DISCORD_TOKENが設定されていません！")
                bot_running = False
                return
            
            if main.CHANNEL_ID == 0:
                print("警告: CHANNEL_IDが設定されていません")
            
            # ★重要: main.pyから新しいclientインスタンスを取得
            # リトライ時は新しいインスタンスが必要
            if retry_count > 0:
                print("新しいclientインスタンスを作成しています...")
                # main.pyを再読み込みして新しいclientを取得
                import importlib
                importlib.reload(main)
            
            bot_running = True
            retry_count = 0  # 成功したらカウントリセット
            
            # ★client.run()は1回しか呼べないので、ここで実行
            main.client.run(main.DISCORD_TOKEN)
            
        except discord.errors.HTTPException as e:
            if e.status == 429:
                retry_count += 1
                print("=" * 50)
                print(f"⚠️ レート制限エラー (試行 {retry_count}/{MAX_RETRIES})")
                print("Discord側で一時的にブロックされています")
                
                if retry_count < MAX_RETRIES:
                    wait_time = RETRY_DELAY * retry_count
                    print(f"{wait_time}秒後に再試行します...")
                    print("=" * 50)
                    bot_running = False
                    time.sleep(wait_time)
                    # whileループで再試行（新しいclientで）
                else:
                    print("最大リトライ回数に達しました")
                    print("手動で再デプロイしてください")
                    print("=" * 50)
                    bot_running = False
                    return
            else:
                print(f"Discord HTTPエラー: {e}")
                bot_running = False
                return
                
        except Exception as e:
            print(f"Bot起動エラー: {e}")
            import traceback
            traceback.print_exc()
            bot_running = False
            return

def signal_handler(sig, frame):
    """シャットダウンシグナルを処理"""
    print("シャットダウンシグナルを受信しました")
    global bot_running
    bot_running = False
    sys.exit(0)

if __name__ == "__main__":
    # シグナルハンドラを設定
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("=" * 50)
    print("Discord Bot with Flask (Render用)")
    print("=" * 50)
    
    # Discord botを別スレッドで起動
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    print("Flaskサーバーを起動しています...")
    
    # Flaskサーバーを起動
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
