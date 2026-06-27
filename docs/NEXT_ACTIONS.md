# Next Actions

## 今すぐやる順番

1. app.py と app_next.py の差分確認
2. どちらを正にするか決める
3. app_next.py を正式採用するなら app.py へ反映
4. RUDIA/ルディア表記の除去
5. Gmail OAuth の固定 user_id/company_id 除去
6. UI設計に沿ってホームから整える
7. ファイル分割開始

## 最優先修正

### 1. gmail_oauth_web.py

残存：

user_id = 1
company_id = 1

これを session_state の user_id / company_id から受け取る形へ変更。

### 2. 旧 要対応タブ

現状 if False で退避済み。

販売前に完全削除または別ファイル保管。

### 3. 表記

利用者画面では

- RUDIA
- ルディア

禁止。

すべて

- AI

に統一。

### 4. app.py / app_next.py

二重管理は危険。

どちらかを正本にする。

推奨：

- app_next.py を確認
- 問題なければ app.py に昇格
- app_next.py は開発用に戻す
