# Profit Radar Refactor Plan

## 目的

app.py / app_next.py が肥大化しているため、機能単位で分割する。

現在：

- app.py 約2815行
- app_next.py 約2517行

目標：

- app.py は起動・認証・タブ呼び出しだけ
- 各画面は modules に分離

## 推奨ディレクトリ

ProfitRadar_RUDIA/
  app.py
  modules/
    auth_ui.py
    home_ui.py
    reply_ui_main.py
    customer_ui.py
    results_ui.py
    gmail_settings_ui.py
    developer_ui.py
    shared_ui.py
  services/
    lead_service.py
    action_service.py
    customer_service.py
    revenue_service.py
    timeline_service.py
  docs/

## 分割順

### Step 1

shared_ui.py 作成

### Step 2

auth_ui.py 作成

### Step 3

gmail_settings_ui.py 作成

### Step 4

home_ui.py 作成

### Step 5

reply_ui_main.py 作成

### Step 6

customer_ui.py 作成

### Step 7

results_ui.py 作成

### Step 8

developer_ui.py 作成

## 注意

一気に分割しない。

理由：

- Streamlitのsession_state依存がある
- DB関数がapp.py内に混在
- UIと処理が密結合
- Gmail送信/返信検知は壊すと危険

まずは設計固定。
次に1画面ずつ移動。
