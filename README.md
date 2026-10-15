# LayerMap

YAMLで社内LANのL1・L2・L3と層間の対応を記述し、SVG図面を生成する試作です。
機器名、メーカー、型番、シリアルNo、設置場所も表示します。現在はCLIで、Web UIは未実装です。
データ形式は独自の `lan-example/v1` です。サンプルの機器情報はすべて架空です。

## 開発環境

開発の正本はDebianの `/home/kudo/layermap` です。
必要なソフトはGit、Docker Engine、Docker Composeです。ホストへのPythonパッケージのインストールは不要です。
推奨は `docker compose`。既存の `docker-compose` でも同じ設定を利用できます。
コンテナは常駐させず、テスト・生成の都度実行します。公開ポートはありません。

```sh
cd /home/kudo/layermap
git status --short --branch
docker-compose ps
docker compose build test
docker compose run --rm test
```

Dockerイメージの初回ビルドは、PythonイメージとPyYAMLの取得にネットワーク接続を使います。
実行時のコンテナはネットワークなし・非root・ソース読み取り専用です。
イメージには `.dockerignore` で指定したファイルだけをコピーします。

## 図面の生成

```sh
mkdir -p artifacts
docker compose run --rm generate
```

出力は `artifacts/lan-sample.svg` です。生成物はGitに登録しません。
別のYAMLを使う場合は作業フォルダー内に配置して指定します。

```sh
docker compose run --rm generate python generate_diagram.py your-network.yaml -o /output/your-network.svg
```

保存時の再生成：

```sh
docker compose run --rm generate python generate_diagram.py lan-sample.yaml -o /output/lan-sample.svg --watch
```

終了はCtrl+C。ブラウザーはSVGを再読み込みしてください。
Debianと異なるUIDで使う場合は、`LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)` をコマンドの前に設定します。

## 検証範囲と制約

テストはDocker内で実行します。5件のテストで変更反映、構成追加、ID参照、VLAN/IPの不整合、監視時の更新とエラー時のSVG保持を確認します。
物理到達性やファイアウォールポリシーを検証するシミュレーターではありません。
詳細は [サンプル仕様](lan-sample-README.md) を参照してください。

## 開発ルール

変更前にGit状態を確認し、変更内容を説明して承認を得ます。
Docker内で検証し、必要に応じてブラウザーで確認してからcommit・GitHub pushします。
通常の完了範囲はGitHub pushまでです。
SSH秘密鍵、接続情報メモ、ローカル依存、生成画像はリポジトリに含めません。
