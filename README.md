# Genre_Shifter

MP3/WAV/FLACをGemini APIで音楽解析し、Suno v4.5向けStyleプロンプトをTop3形式で自動提案するPyQt6デスクトップアプリです。

オリジナル曲のStyleプロンプトも同時生成するため、「元の曲がどう変化するか」をプロンプトレベルで比較しながらSunoに貼り付けて使えます。

---

## 機能

- **オリジナル曲の解析** — ジャンル・使用楽器・ボーカルタイプ・BPM・拍子・調性・エネルギーレベル・プロダクションスタイルを抽出
- **オリジナル曲のStyleプロンプト生成** — 元の曲をそのまま再現するSuno用Styleプロンプトを生成・コピー
- **Top3リアレンジ提案** — コアアイデンティティを保ちながら異なるジャンルへ変換する3案を提示。各案にSunoプロンプトが付属
- **ワンクリックコピー** — 各プロンプトをクリップボードにコピーしてSunoにそのまま貼り付け可能
- **日本語・英語UI切り替え** — ボタン1つで表示言語を切り替え

<img width="862" height="827" alt="image" src="https://github.com/user-attachments/assets/e0d29b76-3434-45da-8af4-fb8f5083ea12" />

---

## 動作環境

- Python 3.10以上
- Windows / macOS / Linux
- Gemini APIキー（Google AI Studioで取得）

---

## セットアップ

### 1. 依存パッケージのインストール

```bash
pip install PyQt6 google-genai
```

### 2. APIキーの取得

[Google AI Studio](https://aistudio.google.com/) にGoogleアカウントでログインし、「Get API key」→「Create API key」でキーを発行します。

### 3. 環境変数の設定

**コマンドプロンプト（Windows）**

```cmd
setx GEMINI_API_KEY "your_api_key_here"
```

**PowerShell（Windows）**

```powershell
[System.Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "your_api_key_here", "User")
```

**macOS / Linux**

```bash
echo 'export GEMINI_API_KEY="your_api_key_here"' >> ~/.zshrc
source ~/.zshrc
```

設定後はターミナルを再起動してください。

---

## 使い方

```bash
python main.py
```

1. 「ファイルを選択」ボタンでMP3/WAV/FLACを選択（上限100MB）
2. 「解析スタート」ボタンを押す
3. 20〜60秒ほどで結果が表示される
4. オリジナル曲またはTop3各案のコピーボタンでプロンプトをコピー
5. SunoのStyleフィールドに貼り付けて生成

---

## ファイル構成

```
auto_remix_checker/
├── main.py          # アプリ本体
├── lang/
│   ├── ja.json      # 日本語UIテキスト
│   └── en.json      # 英語UIテキスト
└── docs/
    └── fix-plan.md  # QA修正プラン
```

---

## 技術仕様

| 項目 | 内容 |
|---|---|
| GUI | PyQt6 |
| 解析モデル | Gemini 2.0 Flash |
| アップロード先 | Gemini Files API（Googleドライブとは別の一時ストレージ） |
| ファイル保持 | 解析完了後に即座に削除（最大48時間で自動削除） |
| 対応フォーマット | MP3 / WAV / FLAC |
| ファイルサイズ上限 | 100MB |
| Sunoプロンプト長 | 200〜250ワード（Suno v4.5の1000文字上限に対応） |

---

## プロンプト設計について

Sunoで効果的なStyleプロンプトになるよう、Geminiへの指示に以下を組み込んでいます。

- 奏法・音色レベルでの楽器記述（例："prominent slap bass line"）
- ギターソロなど特徴的なパートの個別記述
- 和声キャラクターの明示（例："major seventh and minor ninth chords"）
- BPM・拍子・調性・プロダクション詳細の網羅
- タグ羅列ではなく流れのある文章形式

---

## 注意事項

- Gemini APIの無料枠には1日あたりのリクエスト数に制限があります（2025年12月以降に制限が縮小）。頻繁に使用する場合は有料枠への移行を推奨します
- APIキーはコードに直接記述せず、環境変数で管理してください
- アップロードした音楽ファイルはGemini Files APIの一時ストレージに保存されますが、解析完了後に即座に削除されます
