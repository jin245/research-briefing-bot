# Project Instructions for Claude Code

このファイルは、Claude Code がこのプロジェクトで作業する際に最優先で守るべきルールを定義する。
すべての実装・修正・提案・レビューにおいて、以下のルールに従うこと。

---

## プロジェクト概要

- プロダクト: Research Briefing Bot（arXiv 新着論文 + 技術ブログの Daily Briefing Slack 通知）
- 技術スタック: Python 3.11 + GitHub Actions + Slack Bot Token (Web API)
- 状態管理: リポジトリ内の state.json（外部DBは使用しない）
- フェーズ: MVP（検証段階）

---

## 絶対ルール（違反は許容されない）

1. シークレットを安全に扱うこと
   - Webhook URL、APIキー、トークン等の秘密情報を、コード内にハードコードしてはならない
   - シークレットをログ、stdout、stderr、コメント、コミットメッセージに出力してはならない
   - シークレットは環境変数（または .env ファイル経由）から読み取るだけにすること
   - .env ファイルの内容を Read ツールや Bash ツールで読み取ったり表示したりしてはならない

2. Slack 連携は Bot Token（Web API）方式で行うこと
   - 許可スコープ: `chat:write`, `files:write` のみ
   - インタラクティブ機能（ボタン応答、モーダル、スラッシュコマンド、Request URL）は禁止
   - チャンネルの自動作成は禁止

3. 外部データベースを使用してはならない
   - 状態管理は state.json のみで行う
   - SQLite、Redis、PostgreSQL、S3、GCS 等のデータストアを導入してはならない
   - GitHub Issues や Wiki を状態管理に流用してはならない

4. MVP スコープ外の機能を実装してはならない
   - PDF 解析や全文取得（※ Markdown/PDF ブリーフィング生成は許可）
   - 著者の所属機関の推定やスクレイピング
   - LLM API（OpenAI API、Claude API 等）を使った要約・分類
   - モデル名（GPT-4、Gemini、LLaMA 等）による企業判定
   - Slack のインタラクティブ機能（ボタン応答、モーダル、スラッシュコマンド）
   - ユーザー認証やアクセス制御
   - 複数チャンネルへの通知振り分け
   - ダッシュボードやウェブ UI
   - メール通知やその他の通知チャネル

5. 仮想環境を使用すること
   - パッケージのインストールは必ず .venv 内で行う（.venv/bin/pip を使用）
   - グローバル環境への pip install は禁止

---

## 禁止事項

- .env ファイルの中身をユーザーに確認・表示すること
- Bot Token を含む文字列を生成・補完・出力すること
- state.json 以外の永続化手段を提案すること（MVP フェーズ中）
- 学術論文の代替 API（Semantic Scholar、OpenAlex 等）を追加すること
- requirements.txt に記載されていない依存を暗黙的に使用すること
- git push や git push --force を確認なしに実行すること

---

## 違反時の振る舞い

- ルールに違反する実装が必要になった場合、実装を続行してはならない
- どのルールに違反するかを具体的に説明し、ユーザーに判断を委ねること
- ユーザーが明示的にルールの例外を許可した場合のみ、その範囲で実装してよい
- 判断に迷う場合は「推測で実装」せず、必ずユーザーに質問すること

---

## スコープ外提案のルール

- MVP スコープ外の改善案を提案すること自体は許可する
- ただし必ず「これは MVP 外の提案です」と明示すること
- スコープ外の提案を実装に混ぜてはならない

---

## セキュリティルール詳細

### シークレット管理
- シークレットは環境変数からのみ取得する（os.environ.get） → 単一の取得経路に統一し事故を防ぐ
- 管理対象シークレット: `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID`
- .env ファイルは .gitignore に含め、リポジトリにコミットしない → 秘密情報の流出を防ぐ
- ログや標準出力にシークレットを含む文字列を出力しない → Actions ログからの漏洩を防ぐ

### 依存パッケージ
- 使用する外部パッケージは requirements.txt に明記されたもののみ → サプライチェーンリスクの最小化
- 現在の許可パッケージ:
  - feedparser: arXiv Atom feed / ブログ RSS の解析
  - requests: Slack Web API への HTTP POST / 外部 API 通信
  - python-dateutil: arXiv / ブログの日時文字列パース
  - python-dotenv: .env ファイルからの環境変数読み込み
  - PyYAML: config.yml / config.example.yml の読み込み
  - xhtml2pdf: HTML → PDF 変換（PDF ブリーフィング生成用）

---

## Slack 連携ルール詳細

### 通知方式
- 即時通知は行わない。毎朝 07:00 JST に1通の Daily Briefing を投稿する
- 日中の収集ジョブ（毎時）は Slack への投稿を行わない

### ブリーフィングフォーマット
- Slack Block Kit を使用し、1メッセージで投稿する
- 構成:
  - Header: "Daily AI Research Briefing — YYYY-MM-DD (JST)"
  - Section A: 🔥 High Priority（企業ブログ新着）
  - Section B: 🧪 Notable arXiv（キーワードマッチした arXiv 論文）
  - Section C: 🔗 Blog ↔ arXiv Updates（ブログ⇄arXiv のクロスリファレンス）
  - Footer: 収集範囲・件数サマリ
- 各セクション最大 5 件表示。超過分はカウント表示
- 要約はタイトル + abstract 先頭 150 文字のルールベース（LLM 禁止）

---

## データ取得ルール詳細

### データソース
- arXiv API（Atom feed）→ 公式 API、追加認証不要
- 技術ブログ RSS（Google Research, DeepMind, OpenAI）→ 公開 RSS フィード
- 学術論文の代替 API（Semantic Scholar、OpenAlex 等）の追加は禁止

### 対象カテゴリ
- cs.AI, cs.LG, stat.ML

### 取得範囲
- 直近 48 時間以内に公開された論文 → Actions の実行失敗や遅延に耐えるバッファ

### 企業キーワードマッチ
- マッチ対象: タイトル、要約（abstract）、著者名の文字列
- 正規表現による単語境界マッチ（Meta, FAIR は大文字小文字区別あり）
- キーワード一覧: Google, DeepMind, Meta, FAIR / Facebook AI Research, OpenAI, Anthropic

---

## 状態管理ルール詳細

- 保存先: リポジトリルートの state.json（gitignore 済み、GitHub Actions では actions/cache で永続化）
- 保存内容:
  - notified_ids（arXiv ID→通知日時）: 収集済み arXiv ID の重複排除用
  - notified_blog_urls（URL→通知日時）: 収集済みブログ URL の重複排除用
  - blog_arxiv_map（arXiv ID→ブログ情報）: ブログ⇄arXiv クロスリファレンス用
  - daily_buffer（日付→{blog_posts, arxiv_papers, linked_papers}）: ブリーフィング用バッファ
- 肥大化防止: arXiv ID は FETCH_HOURS + 24 時間、ブログ関連は 30 日、バッファは 3 日で自動削除

---

## GitHub Actions ルール

- 実行モード:
  - MODE=collect（収集）: cron 15 * * * *（毎時 :15）— arXiv・ブログを取得し state にバッファ蓄積。Slack 投稿なし
  - MODE=brief（ブリーフィング）: cron 0 22 * * *（毎日 22:00 UTC / 07:00 JST）— バッファを集約し Slack に1通投稿
- 手動実行: workflow_dispatch で mode を選択して実行可能
- state.json は actions/cache/restore + actions/cache/save で永続化（コミットしない）
- キャッシュキー: state-v3-{branch}（固定キー、delete-then-save で毎回上書き）
- concurrency グループで同一ブランチの並行実行を防止
- ブリーフィング配信は peek → send → ack の2段階で、送信失敗時にバッファを保持
- SLACK_BOT_TOKEN, SLACK_CHANNEL_ID は GitHub Secrets から環境変数として渡す
- PDF 変換は Python パッケージ（markdown + xhtml2pdf）で行う（外部ツール不要）

---

## 開発環境

- Python 仮想環境: .venv/
- 依存管理: requirements.txt
- ローカル設定: .env（gitignore 済み）
- 実行コマンド: MODE=collect .venv/bin/python src/main.py / MODE=brief .venv/bin/python src/main.py
- モジュール構成: src/ 配下に config.py, arxiv_client.py, blog_client.py, slack.py, state.py, main.py
- 出力ディレクトリ: out/（Markdown/PDF ブリーフィング生成先、gitignore 済み）

---

## コーディング規約

- エラーハンドリング: 例外は握りつぶさず、失敗を GitHub Actions で検知できるようにする
- arXiv API レスポンスのフィールド欠損に対して堅牢に処理する（.get() を使用）
- state.json の肥大化を防ぐため、保持する ID 数に上限を設ける
- git commit のメッセージはConventional Commitsで記述する

---

## 自己チェックリスト

実装・修正を行う前後に、以下を確認すること。NO がある場合は対応方針に従う。

### 実装前

- [ ] この変更は MVP スコープ内か？ → NO: 「MVP 外の提案です」と明示し許可を得る
- [ ] 変更対象のファイルを Read ツールで読んだか？ → NO: 必ず読んでから修正する
- [ ] 要件は明確か？ → NO: 推測せずユーザーに質問する
- [ ] シークレットをハードコードしていないか？ → NO: 環境変数からの読み取りに変更する
- [ ] .env の内容を読み取ろうとしていないか？ → 読み取ろうとしている場合: 即座に中止
- [ ] Slack 連携は Bot Token (Web API) のみか？ → NO: Web API 方式に変更する
- [ ] データソースは arXiv API と許可済みブログ RSS のみか？ → NO: 他のソースを削除する
- [ ] 状態管理は state.json のみか？ → NO: 外部ストレージを削除する
- [ ] pip install は .venv 内か？ → NO: .venv/bin/pip を使用する

### 実装後

- [ ] エラーを握りつぶしていないか？ → NO: bare except を削除し例外を伝播させる
- [ ] API レスポンスのフィールド欠損に堅牢か？ → NO: .get() に変更する
- [ ] requirements.txt にないパッケージを使っていないか？ → NO: 追加するか取りやめる
- [ ] 差分にシークレットが含まれていないか？ → NO: 該当部分を削除する
- [ ] .env が .gitignore に含まれているか？ → NO: .gitignore に追加する
- [ ] MVP スコープ外の機能が混入していないか？ → NO: 分離してユーザーに確認する

### 違反を検出した場合

1. 実装を即座に中止する
2. 違反しているルールを具体的に特定する
3. ユーザーに報告する: どのルールに違反するか、なぜか、代替案はあるか
4. ユーザーの判断を待つ
