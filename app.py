from flask import Flask
import threading
import os
import signal
import sys

# main.pyからbotを起動
import main

app = Flask(__name__)

# Bot起動状態を管理
bot_running = False
bot_thread = None

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
    return {
        "bot_running": bot_running,
        "bot_user": str(main.client.user) if main.client.user else "Not logged in",
        "monitored_sites": len(main.MONITORED_SITES)
    }, 200

def run_bot():
    """別スレッドでDiscord botを起動"""
    global bot_running
    try:
        print("=" * 50)
        print("Discord Botを起動しています...")
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
        
        bot_running = True
        main.client.run(main.DISCORD_TOKEN)
    except Exception as e:
        print(f"Bot起動エラー: {e}")
        import traceback
        traceback.print_exc()
        bot_running = False

def signal_handler(sig, frame):
    """シャットダウンシグナルを処理"""
    print("シャットダウンシグナルを受信しました")
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
