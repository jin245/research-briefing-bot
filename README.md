# Research Briefing Bot

Google / DeepMind / Meta / FAIR / OpenAI / Anthropic に関連する arXiv 新着論文と技術ブログを自動収集し、毎朝 07:00 JST に Daily Briefing として Slack に投稿する GitHub Actions ベースのボットです。Block Kit メッセージに加え、同内容の Markdown/PDF ファイルをスレッドにアップロードします。

## 機能

### Daily Briefing（毎朝1通のダイジェスト）

日中の収集（1日3回）と朝のブリーフィング配信（1日1回）を分離した2段階パイプラインで動作します。

**収集モード（MODE=collect）**:
- arXiv API (Atom feed) から cs.AI, cs.LG, stat.ML カテゴリの新着論文を取得
- Google Research, DeepMind, OpenAI の技術ブログ RSS を監視
- 収集したアイテムを `state.json` の daily_buffer に蓄積（Slack への投稿は行わない）

**ブリーフィング配信モード（MODE=brief）**:
- daily_buffer に蓄積されたデータを集約し、Slack に Daily Briefing を投稿
- 同内容の Markdown / PDF ファイルをスレッドにアップロード
- 投稿後、バッファをクリアして次のサイクルへ

### ブリーフィング構成

```
Daily AI Research Briefing — 2026-02-11 (JST)
────────────────────────────────────────
🔥 High Priority — Tech Blog Posts (3)
   新着ブログ記事（Google Research, DeepMind, OpenAI）
────────────────────────────────────────
🧪 Notable arXiv Papers (5)
   キーワードマッチした arXiv 論文
────────────────────────────────────────
🔗 Blog ↔ arXiv Updates (2)
   ブログで言及された arXiv 論文のクロスリファレンス
────────────────────────────────────────
📊 cs.AI, cs.LG, stat.ML · Past 48h · 件数サマリ
```

各セクション最大 5 件表示。超過分はカウント表示されます。

### キーワードマッチ
- 正規表現による単語境界マッチで偽陽性を低減（例: "meta-learning" が Meta にヒットしない）
- 対象: Google, DeepMind, Meta, FAIR / Facebook AI Research, OpenAI, Anthropic

### 状態管理
- `state.json` で通知済み arXiv ID・ブログ URL・daily_buffer を管理
- リポジトリには含めず、GitHub Actions では `actions/cache` で永続化
- arXiv ID は 72 時間、ブログ関連は 30 日、バッファは 3 日で自動削除

## クイックスタート（3ステップ）

### 1. リポジトリを Fork

GitHub 上で **Fork** をクリックし、自分のアカウントにコピーします。

> 設定なしでもすぐに動作します。デフォルトで以下の企業・組織に関連する論文とブログを追跡します:
>
> **キーワード**: Google, DeepMind, Meta, FAIR, OpenAI, Anthropic
> **ブログ RSS**: Google Research, DeepMind, OpenAI
> **arXiv カテゴリ**: cs.AI, cs.LG, stat.ML
>
> カスタマイズしたい場合は [追跡対象のカスタマイズ](#追跡対象のカスタマイズ-configyml) を参照してください。

### 2. Slack App を作成し、GitHub Secrets を登録

**Slack App の作成:**

1. [Slack API](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. アプリ名（例: `Research Briefing Bot`）とワークスペースを指定
3. **OAuth & Permissions** → **Bot Token Scopes** に `chat:write` と `files:write` を追加
4. **Install to Workspace** → **Allow**
5. 表示される **Bot User OAuth Token**（`xoxb-...`）をコピー
6. 通知先チャンネルで `/invite @Research Briefing Bot` を実行して Bot を招待
7. チャンネル詳細の最下部から **Channel ID**（`C...`）をコピー

**GitHub Secrets の登録:**

Fork したリポジトリの **Settings** → **Secrets and variables** → **Actions** で以下を追加:

| Secret 名 | 値 |
|---|---|
| `SLACK_BOT_TOKEN` | Bot User OAuth Token（`xoxb-...`） |
| `SLACK_CHANNEL_ID` | 通知先チャンネルの Channel ID（`C...`） |

### 3. 動作確認

1. **Actions** タブ → 左サイドバーでワークフローを選択 → **Run workflow**
2. mode: `collect` で実行（データ収集）
3. 成功したら mode: `brief` で実行（Slack に投稿）
4. Slack チャンネルにブリーフィングが届けば完了

以降は自動でスケジュール実行されます:

- **1日3回（06:00, 14:00, 21:00 UTC）** — 収集ジョブ（`collect`）
- **毎日 22:00 UTC（07:00 JST）** — ブリーフィング配信（`brief`）

## ローカル実行

```bash
# 依存インストール
pip install -r requirements.txt

# Bot Token と Channel ID を環境変数にセット
export SLACK_BOT_TOKEN="xoxb-..."
export SLACK_CHANNEL_ID="C0123..."

# 1. 収集（Slack投稿なし、state.jsonにバッファ蓄積）
MODE=collect python src/main.py

# 2. ブリーフィング配信（バッファ内容をSlackに投稿 + md/pdfアップロード）
MODE=brief python src/main.py
```

> **PDF 生成**: `requirements.txt` に含まれる `xhtml2pdf` で生成されます。外部ツールのインストールは不要です。

## リポジトリ構成

```
.
├── .github/workflows/
│   └── notifier.yml       # GitHub Actions ワークフロー（収集+ブリーフィング）
├── src/
│   ├── main.py            # エントリーポイント（MODE分岐）
│   ├── arxiv_client.py    # arXiv API クライアント
│   ├── blog_client.py     # 技術ブログ RSS クライアント
│   ├── slack.py           # Daily Briefing Block Kit 生成・送信・PDF 生成
│   ├── state.py           # 状態管理 (state.json + daily_buffer)
│   └── config.py          # 設定定数（config.yml をロード）
├── .env.example           # 環境変数テンプレート
├── config.example.yml     # 追跡対象の設定テンプレート（デフォルト値）
├── out/                   # 生成された Markdown/PDF ブリーフィング（gitignore 済み）
├── requirements.txt       # Python 依存パッケージ
├── LICENSE                # MIT License
└── README.md

# state.json は実行時に生成される（gitignore 済み、Actions では actions/cache で永続化）
```

## state.json スキーマ

```json
{
  "notified_ids": { "<arXiv ID>": "<timestamp>" },
  "notified_blog_urls": { "<URL>": "<timestamp>" },
  "blog_arxiv_map": { "<arXiv ID>": { "blog_url": "...", "blog_title": "...", "blog_source": "...", "added_at": "..." } },
  "daily_buffer": {
    "YYYY-MM-DD": {
      "blog_posts": [ { "title": "...", "url": "...", "source": "...", ... } ],
      "arxiv_papers": [ { "arxiv_id": "...", "title": "...", ... } ],
      "linked_papers": [ { "paper": {...}, "blog_info": {...} } ]
    }
  }
}
```

## GitHub Actions スケジュール

| モード | Cron | 時刻 | 動作 |
|--------|------|------|------|
| collect | `0 6,14,21 * * *` | 1日3回 (06:00, 14:00, 21:00 UTC) | arXiv・ブログ収集、バッファ蓄積 |
| brief | `0 22 * * *` | 22:00 UTC (07:00 JST) | Daily Briefing を Slack に投稿 |

- `workflow_dispatch` により手動実行も可能（mode を選択）
- `state.json` は `actions/cache/restore` + `actions/cache/save` で永続化（固定キー `state-v3-{branch}`、delete-then-save で更新）
- concurrency グループにより同一ブランチの並行実行を防止
- ブリーフィング送信失敗時はバッファを保持し、次回再送信

## 追跡対象のカスタマイズ (config.yml)

`config.example.yml` をコピーして `config.yml` を作成し、追跡対象をカスタマイズできます。

> **注意**: `config.yml` は `.gitignore` に含まれているため、ローカル実行専用です。
> GitHub Actions（CI）では `config.example.yml` のデフォルト値が使われます。
> CI でもカスタマイズしたい場合は `config.example.yml` を直接編集してください。

```bash
cp config.example.yml config.yml
# config.yml を編集
```

### YAML 構造

```yaml
# キーワード（arXiv 論文のタイトル・要約・著者名に対するマッチ）
keywords:
  - label: "Google"
    pattern: "Google"                # 単純な文字列でOK（自動で単語境界マッチになる）
  - label: "Meta"
    pattern: "Meta"
    case_sensitive: true             # 省略時 false（大文字小文字を区別しない）
  - label: "Facebook AI Research"
    pattern: "Facebook AI Research"
    display_as: "FAIR"               # 省略時 label が表示名
  - label: "Special"
    pattern: '\bGoog[le]{2}\b'
    raw_regex: true                  # 高度な正規表現を使う場合のみ true にする

# 技術ブログ RSS フィード
blog_feeds:
  - source: "Google Research"
    url: "https://blog.research.google/feeds/posts/default?alt=rss"

# arXiv カテゴリ
arxiv_categories:
  - "cs.AI"
  - "cs.LG"
  - "stat.ML"
```

### キーワードの書き方

- **通常**: `pattern` に検索したい文字列をそのまま書くだけでOKです。自動的に `re.escape` + 単語境界マッチ（`\b...\b`）が適用されます
- **高度な正規表現**: `raw_regex: true` を指定すると、`pattern` がそのまま正規表現として使われます（エスケープや単語境界の自動付与は行われません）

### 設定ファイルの優先順位

1. `config.yml`（ユーザーカスタマイズ、gitignore 済み）
2. `config.example.yml`（リポジトリ同梱のデフォルト値）
3. ハードコードされたデフォルト（どちらのファイルも存在しない場合）

- YAML が不正な場合は `ValueError` で即座に失敗します

## トラブルシューティング

### ブリーフィングが来ない

1. **SLACK_BOT_TOKEN / SLACK_CHANNEL_ID を確認**: GitHub Secrets に正しい値が設定されているか、Bot がチャンネルに招待されているか確認してください
2. **収集ジョブが動いているか確認**: Actions ログで collect モードのジョブが正常に完了しているか確認してください
3. **バッファが空**: 収集対象の新着がない場合でもブリーフィングは送信されます（各セクションに「該当なし」と表示）
4. **state.json をリセット**: GitHub Actions の **Actions** → **Caches** からキャッシュを削除してください

### 収集ジョブがエラーになる

1. **arXiv API の遅延**: arXiv のインデックス更新は数時間遅れることがあります
2. **ブログ RSS の取得失敗**: 各フィードの取得失敗は個別にログ出力され、他のフィードには影響しません
3. **Actions ログを確認**: GitHub リポジトリの **Actions** タブから実行ログを確認してください

### state.json が肥大化する

`state.py` で arXiv ID は 72 時間、ブログ関連は 30 日、daily_buffer は 3 日より古いエントリを自動削除しています。通常運用では問題になりません。

### arXiv API のレート制限

arXiv API には明示的なレート制限はありませんが、礼儀として各リクエスト後に 1 秒のスリープを入れています。
