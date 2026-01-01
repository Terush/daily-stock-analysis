# 25MA Trend Follow Bot（商社版）

商社銘柄（丸紅・三井物産・三菱商事・双日）の株価データを自動取得し、25日移動平均線とゴールデンクロス/デッドクロスに基づいた売買シグナルを検知するシステムです。

## 機能

- Yahoo Financeから自動で株価データを取得
- 25日移動平均線による買い/売りシグナル判定
- シグナル発生時のメール通知
- Webページでのダッシュボード表示（GitHub Pages対応）
- ポートフォリオ状態の自動管理

## システム要件

- Python 3.8以上
- インターネット接続
- Gmailアカウント（メール通知用）

## インストール

### 1. リポジトリのクローン

```bash
git clone <your-repository-url>
cd B_Stock_app
```

### 2. 仮想環境の作成（推奨）

```bash
python3 -m venv venv
source venv/bin/activate  # Windowsの場合: venv\Scripts\activate
```

### 3. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

## 設定

### 1. 環境変数ファイルの作成

`.env.example`をコピーして`.env`ファイルを作成します。

```bash
cp .env.example .env
```

### 2. メール設定の編集

`.env`ファイルを編集して、メール設定を行います。

```env
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_FROM=your-email@gmail.com
EMAIL_PASSWORD=your-app-password
EMAIL_TO=recipient@example.com
AUTO_GIT_PUSH=false
```

#### Gmailアプリパスワードの取得方法

1. Googleアカウントの[アプリパスワード](https://myaccount.google.com/apppasswords)にアクセス
2. 2段階認証を有効化（必須）
3. アプリパスワードを生成
4. 生成されたパスワードを`EMAIL_PASSWORD`に設定

### 3. GitHub Pages設定（オプション）

Webページを公開する場合:

1. GitHubでリポジトリを作成
2. リポジトリ設定 → Pages → Source: `main` branch, `/docs` folder
3. `.env`で`AUTO_GIT_PUSH=true`に設定

## 使い方

### 手動実行

```bash
python main.py
```

実行すると以下の処理が行われます:

1. 4銘柄の株価データを取得
2. 25日移動平均線を計算
3. 買い/売りシグナルを判定
4. シグナルがあればメール送信
5. `docs/index.html`を生成

### 自動実行（cron設定）

毎日17:00に自動実行する例:

```bash
crontab -e
```

以下を追加:

```cron
0 17 * * 1-5 cd /path/to/B_Stock_app && /path/to/venv/bin/python main.py >> logs/bot.log 2>&1
```

## 売買ロジック

### 買いシグナル（AND条件）

1. 現在値 > 25日移動平均線
2. 前日終値 <= 前日25日移動平均線（ゴールデンクロス）
3. 25日移動平均線が上向き（当日MA > 前日MA）

### 売りシグナル（OR条件）

1. **デッドクロス**: 現在値 < 25日移動平均線 かつ 前日終値 >= 前日25日移動平均線
2. **損切り**: (現在値 - エントリー価格) / エントリー価格 <= -5%

## ファイル構成

```
B_Stock_app/
├── main.py                 # メイン実行スクリプト
├── config.py               # 設定ファイル
├── .env                    # 環境変数（Git管理外）
├── .env.example            # 環境変数のサンプル
├── portfolio_status.json   # ポートフォリオ状態
├── requirements.txt        # 依存パッケージ
├── templates/
│   └── index.html         # HTMLテンプレート
└── docs/
    └── index.html         # 生成されたWebページ
```

## トラブルシューティング

### メールが送信されない

- `.env`ファイルの設定を確認
- Gmailの2段階認証とアプリパスワードを確認
- ファイアウォール設定を確認

### 株価データが取得できない

- インターネット接続を確認
- Yahoo Financeのサービス状況を確認
- 銘柄コードが正しいか確認

### HTMLが生成されない

- `templates/index.html`が存在するか確認
- `docs/`ディレクトリの書き込み権限を確認

## 注意事項

- このシステムは投資助言を提供するものではありません
- すべての投資判断は自己責任で行ってください
- 過去のパフォーマンスは将来の結果を保証するものではありません
- `.env`ファイルは絶対にGitにコミットしないでください

## ライセンス

このプロジェクトは個人利用を目的としています。

## サポート

問題が発生した場合は、イシューを作成してください。
