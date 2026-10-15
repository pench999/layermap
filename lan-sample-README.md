# 社内LANのレイヤー別構成サンプル

`lan-sample.yaml` は説明用の独自データモデルです。既存の標準規格や作図ツールの入力仕様ではありません。
`lan-sample.svg` は `generate_diagram.py` がYAMLから生成する図です。

## 生成方法

Python 3.10以降を使用します。初回のみ依存ライブラリをインストールします。

```powershell
python -m pip install -r requirements.txt
```

YAMLを編集・保存したあと、次のコマンドで図を更新します。

この作業環境では依存ライブラリを用意済みです。PowerShellで次を実行できます（Pythonとローカル依存を自動選択）：

```powershell
.\generate-diagram.ps1
```

通常のPython環境で実行する場合：

```powershell
python generate_diagram.py lan-sample.yaml
```

出力先は同名のSVGです。ブラウザーで開いて確認できます。別名で保存する場合：

```powershell
python generate_diagram.py lan-sample.yaml -o another-diagram.svg
```

自動配置は機器ごとの列と層ごとの行を基本とします。機器、ポート、VLAN、サブネット、経路、層間対応の増減を反映します。
保存のたびに再生成する場合は、監視モードで起動します。終了はCtrl+Cです。SVGをブラウザーで開いている場合は再読み込みしてください。

```powershell
.\generate-diagram.ps1 -Watch
# または
python generate_diagram.py lan-sample.yaml --watch
```

監視中にYAMLが不正な状態になった場合は、最後に正常生成したSVGを保持し、次の保存時に再検証します。
図はローカルで生成し、外部サービスへ構成情報を送信しません。
Web版・DebianのDocker実行方法はREADME.mdを参照してください。ホストのPythonで実行する場合はrequirements.txtの依存をインストールしてください。

検証：Docker内で `python -m unittest discover -v`（README.mdを参照）

## 構成

- 業務PC：VLAN 10、192.168.10.10/24
- 来客PC：VLAN 20、192.168.20.10/24
- SW01：端末側はアクセスポート、ゲートウェイ側はタグ付きトランク
- GW01：一つのLANポートにVLAN 10と20のサブインターフェースを設定。各セグメントのゲートウェイは末尾 .1

## 読み方

機器名（name）、メーカー（manufacturer）、型番（model）、シリアルNo（serial_number）、設置場所（location）をdevicesに保持します。
これらはすべて架空の値です。L1図の下段に、固定IDとともに各機器の現在の情報を表示しています。
交換履歴は保持せず、交換時は同じidの属性を更新します。機器名を変更しても各層の参照は維持できます。

- L1は物理ポートとケーブルを記述します。
- L2はVLAN、ポートのタグ設定、スイッチ内の転送関係を記述します。
- L3はIPインターフェース、所属サブネット、端末のデフォルト経路を記述します。
- bindingsは層をまたぐ対応です。物理接続でも通信経路でもありません。
- 図の横線はレイヤーごとに意味が異なります。紫の破線は層間の対応です。

例えば業務PCの経路を調べる場合、pc-a.ip → pc-a.l2 → pc-a.eth0 → cable-a → sw01.p1 と追えます。
L2ではsw01.access1からVLAN 10の転送関係を経てsw01.trunkへ進みます。
アップリンクの先はgw01.trunkで、VLAN 10はgw01.v10（192.168.10.1）に対応します。
L3の通信は一度L1を通った後にL2へ移るという意味ではありません。これらは同じ通信を異なる観点で説明しています。

## 範囲と制約

WAN、NAT、DHCP、DNS、管理用アドレス、IPv6、LAG、VRF、冗長構成は今回の範囲外です。
ゲートウェイのVLAN間転送の許可・拒否は未定義なので、来客LANの分離ポリシーまで表現した例ではありません。
VLAN IDとサブネットの一対一対応はこの構成だけの設計です。
IDの重複・参照先、機器の所属、層間のVLAN整合性、IPプレフィックスとサブネット、経路の次ホップを検証します。
検証に失敗した場合はエラー終了し、既存のSVGは更新しません。型・必須フィールド・未定義フィールドの検証はnetwork_model.pyでCLIとWebに共通化しています。
L2のVLAN所属線は所属を示し、物理的な到達性を保証するものではありません。物理的に切断されたVLANの検出は未実装です。
大規模構成では線が交差するため、この描画方式は小規模LANの仕様検証を想定しています。
