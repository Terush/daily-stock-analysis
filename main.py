#!/usr/bin/env python3
"""
25MA Trend Follow Bot - Main Script
商社銘柄の売買シグナルを検知し、メール通知とWebページ公開を行う
"""

import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import yfinance as yf
from jinja2 import Template
import subprocess

import config


# 環境変数を読み込む
load_dotenv()


def load_portfolio():
    """ポートフォリオ状態を読み込む"""
    if not Path(config.PORTFOLIO_FILE).exists():
        # デフォルトの状態を作成
        portfolio = {
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cash": 30000,
            "holdings": {}
        }
        for stock in config.STOCKS:
            portfolio["holdings"][stock["symbol"]] = {
                "shares": 0,
                "entry_price": 0,
                "date_bought": None
            }
        save_portfolio(portfolio)
        return portfolio

    with open(config.PORTFOLIO_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_portfolio(portfolio):
    """ポートフォリオ状態を保存する"""
    portfolio["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(config.PORTFOLIO_FILE, 'w', encoding='utf-8') as f:
        json.dump(portfolio, f, indent=2, ensure_ascii=False)


def fetch_stock_data(symbol, period='60d'):
    """
    Yahoo Financeから株価データを取得

    Args:
        symbol: 銘柄コード (例: "8002.T")
        period: 取得期間

    Returns:
        pandas.DataFrame: 株価データ
    """
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period)
        return df
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return None


def calculate_ma(df, period=25):
    """
    移動平均線を計算

    Args:
        df: 株価データのDataFrame
        period: 移動平均の期間

    Returns:
        pandas.Series: 移動平均線
    """
    return df['Close'].rolling(window=period).mean()


def check_buy_signal(df, ma):
    """
    買いシグナルをチェック

    買い条件 (AND):
    1. 現在値 > 25日移動平均線
    2. 前日終値 <= 前日25日移動平均線（ゴールデンクロス）
    3. 25日移動平均線の傾きが上向き（当日MA > 前日MA）

    Args:
        df: 株価データのDataFrame
        ma: 移動平均線のSeries

    Returns:
        bool: 買いシグナルの有無
    """
    if len(df) < 2 or len(ma) < 2:
        return False

    current_price = df['Close'].iloc[-1]
    prev_price = df['Close'].iloc[-2]
    current_ma = ma.iloc[-1]
    prev_ma = ma.iloc[-2]

    # 条件1: 現在値 > 25日移動平均線
    condition1 = current_price > current_ma

    # 条件2: 前日終値 <= 前日25日移動平均線（ゴールデンクロス）
    condition2 = prev_price <= prev_ma

    # 条件3: 25日移動平均線の傾きが上向き
    condition3 = current_ma > prev_ma

    return condition1 and condition2 and condition3


def check_sell_signal(df, ma, portfolio, symbol):
    """
    売りシグナルをチェック

    売り条件 (OR):
    1. デッドクロス: 現在値 < 25日移動平均線 かつ 前日終値 >= 前日25日移動平均線
    2. 損切り: (現在値 - エントリー価格) / エントリー価格 <= -5%

    Args:
        df: 株価データのDataFrame
        ma: 移動平均線のSeries
        portfolio: ポートフォリオデータ
        symbol: 銘柄コード

    Returns:
        tuple: (bool, str) 売りシグナルの有無と理由
    """
    if len(df) < 2 or len(ma) < 2:
        return False, ""

    # 保有していない場合は売りシグナルなし
    holding = portfolio["holdings"].get(symbol, {})
    if holding.get("shares", 0) == 0:
        return False, ""

    current_price = df['Close'].iloc[-1]
    prev_price = df['Close'].iloc[-2]
    current_ma = ma.iloc[-1]
    prev_ma = ma.iloc[-2]
    entry_price = holding.get("entry_price", 0)

    # 条件1: デッドクロス
    dead_cross = current_price < current_ma and prev_price >= prev_ma
    if dead_cross:
        return True, "デッドクロス"

    # 条件2: 損切り
    if entry_price > 0:
        loss_rate = (current_price - entry_price) / entry_price
        if loss_rate <= config.STOP_LOSS_THRESHOLD:
            return True, f"損切り ({loss_rate*100:.1f}%)"

    return False, ""


def get_trend_direction(ma):
    """移動平均線の傾きを判定"""
    if len(ma) < 2:
        return "→ 横ばい"

    current_ma = ma.iloc[-1]
    prev_ma = ma.iloc[-2]

    if current_ma > prev_ma:
        return "↗ 上昇"
    elif current_ma < prev_ma:
        return "↘ 下落"
    else:
        return "→ 横ばい"


def send_email(subject, body):
    """
    メールを送信

    Args:
        subject: 件名
        body: 本文
    """
    smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    email_from = os.getenv('EMAIL_FROM')
    email_password = os.getenv('EMAIL_PASSWORD')
    email_to = os.getenv('EMAIL_TO')

    if not all([email_from, email_password, email_to]):
        print("Warning: Email settings not configured in .env file")
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = email_from
        msg['To'] = email_to
        msg['Subject'] = subject

        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(email_from, email_password)
        server.send_message(msg)
        server.quit()

        print(f"Email sent: {subject}")
    except Exception as e:
        print(f"Error sending email: {e}")


def generate_html(stock_results, portfolio):
    """
    HTMLページを生成

    Args:
        stock_results: 各銘柄の分析結果
        portfolio: ポートフォリオデータ
    """
    template_path = Path(config.TEMPLATE_PATH)
    if not template_path.exists():
        print(f"Warning: Template file not found: {template_path}")
        return

    with open(template_path, 'r', encoding='utf-8') as f:
        template_content = f.read()

    template = Template(template_content)

    # テンプレートに渡すデータを準備
    html_content = template.render(
        last_updated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        stocks=stock_results,
        cash=portfolio.get("cash", 0),
        portfolio=portfolio
    )

    output_path = Path(config.OUTPUT_HTML)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"HTML generated: {output_path}")


def git_push():
    """
    変更をGitにコミット＆プッシュ
    """
    try:
        subprocess.run(['git', 'add', 'docs/'], check=True, capture_output=True)
        subprocess.run([
            'git', 'commit', '-m',
            f'Update stock analysis - {datetime.now().strftime("%Y-%m-%d %H:%M")}'
        ], check=True, capture_output=True)
        subprocess.run(['git', 'push'], check=True, capture_output=True)
        print("Changes pushed to GitHub")
    except subprocess.CalledProcessError as e:
        print(f"Git operation failed: {e}")
    except FileNotFoundError:
        print("Git is not installed or not in PATH")


def main():
    """メイン処理"""
    print("=" * 60)
    print("25MA Trend Follow Bot - Starting Analysis")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # ポートフォリオを読み込む
    portfolio = load_portfolio()

    # 各銘柄を分析
    stock_results = []
    signals = []

    for stock in config.STOCKS:
        symbol = stock["symbol"]
        name = stock["name"]

        print(f"\nAnalyzing {name} ({symbol})...")

        # データ取得
        df = fetch_stock_data(symbol)
        if df is None or len(df) < config.MA_PERIOD:
            print(f"  Insufficient data for {symbol}")
            continue

        # 移動平均線を計算
        ma = calculate_ma(df, config.MA_PERIOD)

        # 現在の状態を取得
        current_price = df['Close'].iloc[-1]
        current_ma = ma.iloc[-1]
        trend = get_trend_direction(ma)

        # シグナル判定
        buy_signal = check_buy_signal(df, ma)
        sell_signal, sell_reason = check_sell_signal(df, ma, portfolio, symbol)

        # 判定結果
        if buy_signal:
            judgment = "BUY 🔴"
            signal_type = "買い"
            signals.append({
                "stock": stock,
                "type": "買い",
                "price": current_price,
                "ma": current_ma,
                "reason": "ゴールデンクロス達成 & 傾き上向き"
            })
        elif sell_signal:
            judgment = "SELL 🔵"
            signal_type = "売り"
            signals.append({
                "stock": stock,
                "type": "売り",
                "price": current_price,
                "ma": current_ma,
                "reason": sell_reason
            })
        else:
            judgment = "WAIT"
            signal_type = "待機"

        # 結果を保存
        stock_results.append({
            "symbol": symbol,
            "name": name,
            "rank": stock["rank"],
            "current_price": current_price,
            "ma": current_ma,
            "trend": trend,
            "judgment": judgment,
            "signal_type": signal_type
        })

        print(f"  Price: {current_price:.2f}")
        print(f"  25MA: {current_ma:.2f}")
        print(f"  Trend: {trend}")
        print(f"  Signal: {judgment}")

    # シグナルがあればメール送信
    if signals:
        subject = f"【シグナル点灯】株売買シグナル通知 ({datetime.now().strftime('%Y/%m/%d')})"

        body = f"本日の市場が終了しました。以下のシグナルが出ています。\n\n"

        for sig in signals:
            stock = sig["stock"]
            body += f"■ {stock['name']} ({stock['symbol']})\n"
            body += f"判定: {sig['type']}推奨\n"
            body += f"理由: {sig['reason']}\n"
            body += f"現在値: {sig['price']:.2f}円\n"
            body += f"25MA: {sig['ma']:.2f}円\n\n"

            if sig['type'] == '買い':
                body += "【アクション】\n"
                body += "明日の寄り付き（9:00）に「成行」で購入してください。\n\n"
            elif sig['type'] == '売り':
                body += "【アクション】\n"
                body += "明日の寄り付き（9:00）に「成行」で売却してください。\n\n"

        send_email(subject, body)
    else:
        print("\nNo signals detected today.")

    # HTMLページを生成
    generate_html(stock_results, portfolio)

    # Gitにプッシュ（オプション）
    if os.getenv('AUTO_GIT_PUSH', 'false').lower() == 'true':
        git_push()

    # ポートフォリオを保存
    save_portfolio(portfolio)

    print("\n" + "=" * 60)
    print("Analysis completed successfully")
    print("=" * 60)


if __name__ == "__main__":
    main()
