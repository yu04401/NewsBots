"""
ローカルテスト用の実行スクリプト。

.env ファイルからシークレットを読み込み lambda_handler を呼び出す。
PC 全体の環境変数は変更しない。

使い方:
    python run_local.py
"""
from pathlib import Path
from dotenv import load_dotenv

# このスクリプトと同じディレクトリの .env を読み込む
# override=False: すでにシェルで設定済みの変数は上書きしない
load_dotenv(Path(__file__).parent / ".env", override=False)

# .env の読み込み後に lambda_function をインポートして実行
from lambda_function import lambda_handler  # noqa: E402

if __name__ == "__main__":
    result = lambda_handler({}, None)
    print(result)
