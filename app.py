from flask import Flask
import threading
import os

# main.pyからbotを起動
import main

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!", 200

@app.route('/health')
def health():
    return "OK", 200

def run_bot():
    """別スレッドでDiscord botを起動"""
    main.client.run(main.DISCORD_TOKEN)

if __name__ == "__main__":
    # Discord botを別スレッドで起動
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Flaskサーバーを起動
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)