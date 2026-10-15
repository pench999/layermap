# LayerMap

YAMLで社内LANのL1・L2・L3と層間の対応を記述し、ブラウザーで編集・確認できるWebアプリです。CLIでも同じ検証・描画処理を利用できます。
データ形式は独自の `lan-example/v1` です。サンプルの機器情報はすべて架空です。

## Web版の起動

正本はDebianの `/home/kudo/layermap`。Docker EngineとDocker Composeを使います。PythonやNode.jsをホストに追加する必要はありません。

```sh
cd /home/kudo/layermap
git status --short --branch
docker-compose ps
docker compose up -d --build web
docker compose ps
```

既定の待ち受けはDebian自身の `127.0.0.1:18085` です。別のPCからはSSHトンネルを使用します。

```sh
ssh -N -L 18085:127.0.0.1:18085 kudo@<Debianのホスト名またはIP>
```

ブラウザーで <http://localhost:18085> を開きます。PuTTYを使う場合も、ローカル18085番からDebianの127.0.0.1:18085へのトンネルを設定できます。
明示的にLANへ公開する場合だけ `LAYERMAP_BIND` と `LAYERMAP_PORT` を変更してください。初期版には認証・TLS・共同編集機能がないため、既定はループバックです。

停止：

```sh
docker compose stop web
```

## ブラウザーでできること

- CodeMirrorでYAMLを編集。入力が止まって500ミリ秒後に検証・描画。
- 全レイヤー、L1物理、L2 VLAN、L3 IPの切り替え。単独表示ではレイアウトを再計算。
- 全レイヤー表示時の層間対応の表示・非表示。
- 機器を選択して、対応する各層の要素を強調表示。
- 拡大・縮小・全体表示。
- YAMLファイルの読み込み・ダウンロード、現在の表示のSVGダウンロード。
- エラーの行・列・項目パスを表示。エラーを押すと編集位置へ移動。

不正な入力・通信失敗・描画待ちの間は最後の正常な図を保持し、「現在のYAMLは未反映」または「更新待ち」を表示します。
古い応答は新しい編集を上書きしません。未反映の図のSVGダウンロードは無効になります。YAMLはエラー中でも保存できます。
編集は自動でディスクへ保存しません。「YAMLを保存」またはCtrl/Command+Sでダウンロードしてください。未保存時のファイル置き換え・ページ離脱には確認を表示します。

## データの扱いと上限

YAMLは描画のため同じサーバーへ送信します。サーバーは永続保存せず、本文をログへ記録しません。
フロントエンドとAPIは同一オリジンで提供し、CDNや外部フォントは使いません。
YAMLは256 KiB、機器は24台、全要素は500件、HTTPリクエストは1 MiBまでです。YAMLのエイリアス・重複キーと未定義フィールドは拒否します。
ファイルは手元から読み込み、手元へダウンロードします。サーバーの任意のファイルを読む機能はありません。

## Docker内の検証

```sh
docker-compose ps
docker compose build test
docker compose run --rm test
```

単体/APIテストはネットワークなし・非root・読み取り専用のソースで実行します。
ブラウザーの操作テストもDocker内のPlaywright/Chromiumで行います。

```sh
mkdir -p artifacts/browser
docker compose --profile qa build e2e
docker compose --profile qa run --rm e2e
```

ブラウザーテストは編集反映、エラー時の図面保持、レイヤー切り替え、層間対応、機器強調、ファイル読み書き、古い応答の破棄、モバイル表示を確認します。
デスクトップとモバイルの確認画像は `artifacts/browser/` に生成します。Gitには含めません。
ビルド時は依存取得のためネットワークを使用します。フロントエンドの依存は `frontend/package-lock.json`、Pythonの直接依存は `requirements.txt` で固定します。
ブラウザーテストイメージにはPlaywrightのブラウザーが含まれます。

## CLIでの図面生成

```sh
mkdir -p artifacts
docker compose run --rm generate
# 別の入力ファイル
docker compose run --rm generate python generate_diagram.py your-network.yaml -o /output/your-network.svg
# 保存監視
docker compose run --rm generate python generate_diagram.py lan-sample.yaml -o /output/lan-sample.svg --watch
```

出力は `artifacts/lan-sample.svg` です。実行ユーザーのUID/GIDが1000以外の場合は、Compose起動時に `LOCAL_UID` と `LOCAL_GID` を設定してください。

## 構成と制約

- `network_model.py`：型・参照・VLAN・IP・経路の検証と、行番号付きYAML読み込み。
- `generate_diagram.py`：共通SVG描画とCLI。
- `web_app.py`：FastAPI、描画API、ビルド済みフロントエンドの配信。
- `frontend/`：React / TypeScript / CodeMirror、Playwrightテスト。

これは構成図であり、物理到達性やファイアウォールポリシーを判定するシミュレーターではありません。
L2の線はVLANへの所属・ブリッジの関係を示し、通信可能性を保証しません。大規模な構成や長いラベルでは図が読みづらくなる場合があります。
詳細は [サンプル仕様](lan-sample-README.md) を参照してください。

## 開発ルール

変更前にGit状態を確認し、変更内容を説明して承認を得ます。Docker内で検証し、必要に応じてブラウザーで確認してからcommit・GitHub pushします。
完了範囲は通常GitHub pushまでです。SSH秘密鍵、接続情報メモ、ローカル依存、生成画像はリポジトリに含めません。
