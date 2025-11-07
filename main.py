import discord
from discord.ext import tasks
import requests
from bs4 import BeautifulSoup
import hashlib
import difflib
import os
import json
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

# 環境変数から設定を取得（Koyeb用）
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID', 0))
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', 300))
SHOW_DIFF = os.getenv('SHOW_DIFF', 'True').lower() == 'true'

# MONITORED_SITESを環境変数から取得（JSON形式）
MONITORED_SITES_JSON = os.getenv('MONITORED_SITES', '[]')
try:
    MONITORED_SITES = json.loads(MONITORED_SITES_JSON)
except json.JSONDecodeError:
    print("警告: MONITORED_SITESの解析に失敗しました。空のリストを使用します。")
    MONITORED_SITES = []

# ローカル環境のフォールバック
if not DISCORD_TOKEN or CHANNEL_ID == 0:
    try:
        from config import DISCORD_TOKEN, CHANNEL_ID, CHECK_INTERVAL, SHOW_DIFF, MONITORED_SITES
        print("ローカルのconfig.pyから設定を読み込みました")
    except ImportError:
        print("エラー: 環境変数またはconfig.pyが必要です")
        exit(1)

# Botの設定
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# ヘルスチェック用の簡易HTTPサーバー
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')
    
    def log_message(self, format, *args):
        # ログ出力を抑制
        pass

def run_health_server():
    port = int(os.getenv('PORT', 8000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    print(f"ヘルスチェックサーバー起動: ポート {port}")
    server.serve_forever()

# ヘルスチェックサーバーを別スレッドで起動
health_thread = Thread(target=run_health_server, daemon=True)
health_thread.start()

def get_page_content(url, selector=None):
    """ウェブページのコンテンツを取得"""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 特定の要素のみ取得する場合
        if selector:
            element = soup.select_one(selector)
            if element:
                content = element.get_text(separator='\n', strip=True)
            else:
                print(f"警告: セレクタ '{selector}' が見つかりません")
                content = soup.get_text(separator='\n', strip=True)
        else:
            content = soup.get_text(separator='\n', strip=True)
        
        # 空白行を削除して整形
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        return '\n'.join(lines)
    except Exception as e:
        print(f"エラー ({url}): {e}")
        return None

def get_content_hash(content):
    """コンテンツのハッシュ値を計算"""
    if content is None:
        return None
    return hashlib.md5(content.encode()).hexdigest()

def get_diff(old_content, new_content, max_lines=20):
    """2つのコンテンツの差分を取得"""
    if not old_content or not new_content:
        return None
    
    old_lines = old_content.split('\n')
    new_lines = new_content.split('\n')
    
    # 差分を計算
    diff = list(difflib.unified_diff(
        old_lines, 
        new_lines, 
        lineterm='',
        n=0  # コンテキスト行数
    ))
    
    if len(diff) <= 2:  # ヘッダーのみの場合
        return None
    
    # 追加・削除された行を抽出
    added = []
    removed = []
    
    for line in diff[2:]:  # ヘッダーをスキップ
        if line.startswith('+'):
            added.append(line[1:])
        elif line.startswith('-'):
            removed.append(line[1:])
    
    # 差分メッセージを構築
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

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_websites():
    """定期的に全てのウェブサイトをチェック"""
    channel = client.get_channel(CHANNEL_ID)
    if not channel:
        print("チャンネルが見つかりません")
        return
    
    for site in MONITORED_SITES:
        current_content = get_page_content(site['url'], site.get('selector'))
        
        if current_content is None:
            continue
        
        current_hash = get_content_hash(current_content)
        
        # 初回実行時
        if 'hash' not in site or site['hash'] is None:
            site['hash'] = current_hash
            site['content'] = current_content
            print(f"初回チェック完了: {site['name']}")
            continue
        
        # 更新を検知
        if current_hash != site['hash']:
            print(f"更新を検知: {site['name']}")
            
            # 差分を取得
            diff_msg = None
            if SHOW_DIFF and 'content' in site and site['content']:
                diff_msg = get_diff(site['content'], current_content)
            
            # ハッシュとコンテンツを更新
            site['hash'] = current_hash
            site['content'] = current_content
            
            # 通知を送信
            notification = f"{site.get('mention', '@everyone')}\n{site['message']}\n{site['url']}"
            
            # 差分がある場合は追加
            if diff_msg:
                notification += f"\n\n{diff_msg}"
            
            # Discordのメッセージ長制限（2000文字）を考慮
            if len(notification) > 2000:
                notification = notification[:1900] + "\n\n... (差分が長すぎるため省略されました)"
            
            await channel.send(notification)

@client.event
async def on_ready():
    print(f'{client.user} としてログインしました')
    print(f"監視中のサイト: {len(MONITORED_SITES)}件")
    print(f"チェック間隔: {CHECK_INTERVAL}秒")
    print(f"差分表示: {'有効' if SHOW_DIFF else '無効'}")
    for site in MONITORED_SITES:
        print(f"  - {site['name']}: {site['url']}")
    check_websites.start()

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    
    # !statusコマンド
    if message.content == '!status':
        status_msg = "**📊 現在の監視状況:**\n"
        for i, site in enumerate(MONITORED_SITES, 1):
            status = "✅ 監視中" if site.get('hash') else "⏳ 初期化中"
            status_msg += f"{i}. {site['name']}: {status}\n"
        status_msg += f"\nチェック間隔: {CHECK_INTERVAL}秒"
        await message.channel.send(status_msg)
    
    # !checkコマンド
    elif message.content == '!check':
        await message.channel.send("🔍 手動チェックを開始します...")
        await check_websites()
        await message.channel.send("✅ チェック完了しました。")
    
    # !commandsコマンド
    elif message.content == '!commands':
        commands_msg = """
**🤖 Bot コマンド一覧:**
`!status` - 現在の監視状況を表示
`!check` - 手動で即座にチェックを実行
`!commands` - このコマンド一覧を表示
`!help` - ヘルプメッセージを表示
        """
        await message.channel.send(commands_msg)
    
    # !helpコマンド
    elif message.content == '!help':
        await message.channel.send("たすけて～")

if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
