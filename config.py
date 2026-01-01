"""
25MA Trend Follow Bot - Configuration File
"""

# 監視対象銘柄（優先順位順）
STOCKS = [
    {
        "symbol": "8002.T",
        "name": "丸紅",
        "rank": "SS"
    },
    {
        "symbol": "8031.T",
        "name": "三井物産",
        "rank": "S"
    },
    {
        "symbol": "8058.T",
        "name": "三菱商事",
        "rank": "A"
    },
    {
        "symbol": "2768.T",
        "name": "双日",
        "rank": "B"
    }
]

# 移動平均線の期間
MA_PERIOD = 25

# 損切りライン（-5%）
STOP_LOSS_THRESHOLD = -0.05

# ポートフォリオ状態ファイル
PORTFOLIO_FILE = "portfolio_status.json"

# HTMLテンプレートとアウトプット
TEMPLATE_PATH = "templates/index.html"
OUTPUT_HTML = "docs/index.html"

# メール設定（環境変数から読み込む）
# SMTP_SERVER, SMTP_PORT, EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO は.envで設定
