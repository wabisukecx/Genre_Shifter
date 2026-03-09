import sys
import os
import json
import time
import platform
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QFileDialog, QTextEdit, QMessageBox,
                             QSizePolicy, QFrame, QScrollArea)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QFont

from google import genai
from google.genai import types

# ==========================================
# FIX-04: フォント定数（OS別に自動選択）
# ==========================================
_FONT_FAMILY = (
    "Meiryo"          if platform.system() == "Windows" else
    "Hiragino Sans"   if platform.system() == "Darwin"  else
    "Noto Sans CJK JP"
)

# ==========================================
# 0. 言語ファイルローダー（lang/*.json を読み込む）
# ==========================================
def _load_strings():
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lang")
    strings = {}
    for lang in ("ja", "en"):
        path = os.path.join(base, f"{lang}.json")
        try:
            with open(path, encoding="utf-8") as f:
                strings[lang] = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"言語ファイルが見つかりません: {path}")
    return strings

# FIX-05: 起動時 FileNotFoundError をユーザーフレンドリーなダイアログに変換
try:
    STRINGS = _load_strings()
except FileNotFoundError as e:
    _app = QApplication(sys.argv)
    QMessageBox.critical(None, "起動エラー", str(e))
    sys.exit(1)


# ==========================================
# 1. バックグラウンド解析用スレッド
# ==========================================
class AnalyzerThread(QThread):
    finished_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(str)

    def __init__(self, file_path, api_key, lang="ja"):
        super().__init__()
        self.file_path = file_path
        self.api_key = api_key
        self.lang = lang

    def run(self):
        audio_file = None
        client = genai.Client(api_key=self.api_key)
        s = STRINGS[self.lang]  # 進捗メッセージも現在言語で
        try:
            self.progress_signal.emit(s["status_uploading"])
            # 日本語パス対応: io.BytesIOにラップしてファイル名をASCIIに統一する
            import mimetypes, io
            mime_type = mimetypes.guess_type(self.file_path)[0] or "audio/mpeg"
            with open(self.file_path, "rb") as f:
                audio_bytes = io.BytesIO(f.read())
            audio_bytes.name = "audio" + os.path.splitext(self.file_path)[1]  # ASCIIのファイル名を付与
            audio_file = client.files.upload(
                file=audio_bytes,
                config=types.UploadFileConfig(mime_type=mime_type)
            )

            # FIX-02: タイムアウト上限 5分
            MAX_WAIT_SEC = 300
            elapsed = 0
            while audio_file.state.name == "PROCESSING":
                if elapsed >= MAX_WAIT_SEC:
                    raise TimeoutError(f"ファイル処理がタイムアウトしました ({MAX_WAIT_SEC}秒)")
                time.sleep(2)
                elapsed += 2
                audio_file = client.files.get(name=audio_file.name)

            self.progress_signal.emit(s["status_analyzing"])

            output_lang      = s["prompt_lang"]        # original_analysis の出力言語
            genre_lang       = s["prompt_genre_lang"]  # genre / reason の出力言語

            prompt = f"""
You are a professional music producer and audio analyst.
Analyze the attached audio file directly and output results in JSON format following the requirements below.

[REQUIREMENTS]
1. original_analysis: Extract the "core identity" of the track.
   Write this field in **{output_lang}**. Include:
   - Genre and sub-genre
   - Key instruments and their roles
   - Vocal type and language (if present)
   - Tempo range (BPM estimate)
   - Time signature
   - Key/mode (major, minor, etc.)
   - Energy level and mood
   - Production style (e.g., lo-fi, polished, live-sounding)

2. original_suno_style_prompt: A Suno v4/v5 Style prompt that faithfully represents THIS ORIGINAL TRACK as-is.
   Always in English. Follow the exact same format rules as the recommendation prompts (item 3 below):
   specific instrument techniques, harmonic character, vocal delivery, production details, 200-250 words.
   This allows users to reproduce the original track's style directly in Suno.

3. recommendations: Propose Top 3 re-arrangement ideas that preserve the core identity while fitting a different genre.
   Each item must include:
   - rank: 1-3
   - genre: Genre name in **{genre_lang}**
   - reason: Specific reasoning including instrument substitutions, written in **{output_lang}**
   - suno_style_prompt: A detailed Suno v4/v5 Style prompt in English (always English regardless of UI language).
     This prompt MUST follow Suno's effective style format:
     * Start with a genre/style descriptor phrase (e.g., "Upbeat 1980s-style J-Pop and City Pop track")
     * Describe key instruments with specific playing techniques and adjectives
       (e.g., "prominent slap bass line", "bright synthesized brass stabs", "shimmering electric guitar funk strums")
       Do NOT use vague terms like "punchy bassline" — be specific about technique and timbre
     * If a guitar solo or notable instrumental moment exists, describe it separately
       (e.g., "melodic soaring electric guitar solo with slight overdrive and chorus effect")
     * Describe vocal type, gender, and delivery style if vocals exist
       (e.g., "clean melodic male vocal with smooth earnest tone", "layered vocal harmonies in the chorus")
     * Describe harmonic character if detectable (e.g., "major seventh and minor ninth chords", "pentatonic-based melodies")
     * Describe song structure moments briefly (e.g., "driving verse, high-energy chorus, melodic bridge")
     * Include tempo (e.g., "128 BPM"), time signature, and key/mode
     * Include specific production details (e.g., "gated reverb on snare", "wide stereo field for synthesizers", "polished mix")
     * If Japanese vocals are detected, include "Japanese vocal"
     * If instrumental, include "instrumental"
     * Write as flowing descriptive sentences separated by commas, NOT just a tag list
     * Aim for 200-250 words total (Suno v4.5+ supports up to 1000 characters)
     * Cover all sonic layers: rhythm section, harmony, melody, vocals, effects, structure, production
     * Avoid redundancy, but be thorough — more detail gives Suno more to work with

Output must be JSON only, no additional text.
"""

            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[audio_file, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )

            self.progress_signal.emit(s["status_cleanup"])
            self.finished_signal.emit(response.text)

        except Exception as e:
            self.error_signal.emit(str(e))

        finally:
            if audio_file is not None:
                try:
                    client.files.delete(name=audio_file.name)
                except Exception:
                    pass


# ==========================================
# 2. メインGUIウィンドウ
# ==========================================
class RemixAnalyzerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.lang = "ja"          # 現在の言語
        self._scroll_area = None
        self.selected_file = None
        self.thread = None        # FIX-06: 初期化しておく
        self.initUI()

    # ------------------------------------------
    # 言語切り替え
    # ------------------------------------------
    def _s(self, key: str) -> str:
        """現在言語の文字列を返す。キー欠損時は [key] を返す（FIX-07）"""
        return STRINGS[self.lang].get(key, f"[{key}]")

    def toggle_lang(self):
        self.lang = "en" if self.lang == "ja" else "ja"
        self._apply_lang()

    def _apply_lang(self):
        """全ウィジェットのテキストを現在言語で更新する"""
        s = STRINGS[self.lang]
        self.setWindowTitle(s["window_title"])
        self.btn_lang.setText(s["lang_toggle"])
        self.btn_select_file.setText(s["btn_select"])
        self.btn_analyze.setText(s["btn_analyze"])
        # ファイル未選択のときだけプレースホルダを更新
        if self.selected_file is None:
            self.label_file_path.setText(s["no_file"])
        # ステータスが「待機中」ならそれも更新
        if self.label_status.text() in (STRINGS["ja"]["status_idle"], STRINGS["en"]["status_idle"]):
            self.label_status.setText(s["status_idle"])

    # ------------------------------------------
    # UI構築
    # ------------------------------------------
    def initUI(self):
        self.setWindowTitle(self._s("window_title"))
        self.resize(860, 720)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # --- トップバー（ファイル選択 + 言語トグル） ---
        file_layout = QHBoxLayout()
        file_layout.setSpacing(8)

        self.btn_select_file = QPushButton(self._s("btn_select"))
        self.btn_select_file.clicked.connect(self.select_file)
        self.btn_select_file.setFixedWidth(150)
        self.btn_select_file.setFixedHeight(32)
        self.btn_select_file.setStyleSheet(
            "QPushButton { font-size: 13px; padding: 4px 10px; border: 1px solid #aaa; border-radius: 4px; background: #f5f5f5; }"
            "QPushButton:hover { background: #e0e0e0; }"
            "QPushButton:disabled { color: #aaa; }"
        )

        self.label_file_path = QLabel(self._s("no_file"))
        self.label_file_path.setFixedHeight(32)
        self.label_file_path.setStyleSheet(
            "font-size: 13px; color: #555; background: #fafafa;"
            "border: 1px solid #ddd; border-radius: 4px; padding: 4px 8px;"
        )
        self.label_file_path.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # 言語トグルボタン（現在の言語を表示する）
        self.btn_lang = QPushButton(self._s("lang_toggle"))
        self.btn_lang.clicked.connect(self.toggle_lang)
        self.btn_lang.setFixedSize(60, 32)
        self.btn_lang.setStyleSheet(
            "QPushButton { font-size: 13px; font-weight: bold; border: 1px solid #888;"
            "border-radius: 4px; background: #eef2ff; color: #3a3aaa; }"
            "QPushButton:hover { background: #d8dcff; }"
        )

        file_layout.addWidget(self.btn_select_file)
        file_layout.addWidget(self.label_file_path)
        file_layout.addWidget(self.btn_lang)
        layout.addLayout(file_layout)

        # --- 実行ボタン ---
        self.btn_analyze = QPushButton(self._s("btn_analyze"))
        self.btn_analyze.clicked.connect(self.start_analysis)
        self.btn_analyze.setEnabled(False)
        self.btn_analyze.setFixedHeight(42)
        self.btn_analyze.setStyleSheet(
            "QPushButton { font-size: 16px; font-weight: bold; border-radius: 6px;"
            "  background: #1a73e8; color: white; border: none; }"
            "QPushButton:hover { background: #1558c0; }"
            "QPushButton:disabled { background: #c8d6e5; color: #888; }"
        )
        layout.addWidget(self.btn_analyze)

        # --- ステータス表示 ---
        self.label_status = QLabel(self._s("status_idle"))
        self.label_status.setFixedHeight(28)
        self.label_status.setStyleSheet(
            "font-size: 13px; color: #666; background: #f0f0f0;"
            "border-radius: 4px; padding: 4px 10px;"
        )
        layout.addWidget(self.label_status)

        # --- 結果表示エリア（初期は QTextEdit、結果後は QScrollArea に差し替え）---
        self.text_result = QTextEdit()
        self.text_result.setReadOnly(True)
        self.text_result.setFont(QFont(_FONT_FAMILY, 12))  # FIX-04
        self.text_result.setStyleSheet(
            "QTextEdit { border: 1px solid #ddd; border-radius: 6px;"
            "  background: #ffffff; padding: 8px; line-height: 1.5; }"
        )
        layout.addWidget(self.text_result)

        self.setLayout(layout)

        if not self.api_key:
            QMessageBox.critical(self, "Error", self._s("err_no_key"))
            self.btn_select_file.setEnabled(False)

    # ------------------------------------------
    # イベントハンドラ
    # ------------------------------------------
    def select_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, self._s("file_dialog_title"), '',
            'Audio Files (*.mp3 *.wav *.flac);;All Files (*)'
        )
        if file_name:
            self.selected_file = file_name
            self.label_file_path.setText(file_name)
            self.btn_analyze.setEnabled(True)

    def start_analysis(self):
        # FIX-01: APIキー None チェック（スレッド起動前の最終確認）
        if not self.api_key:
            QMessageBox.critical(self, self._s("err_title"), self._s("err_no_key"))
            return

        # FIX-03: ファイル事前検証
        path = self.selected_file
        if not os.path.isfile(path):
            QMessageBox.critical(self, self._s("err_title"), f"ファイルが見つかりません:\n{path}")
            return
        if not os.access(path, os.R_OK):
            QMessageBox.critical(self, self._s("err_title"), f"ファイルを読み取れません:\n{path}")
            return
        MAX_FILE_MB = 100
        size_mb = os.path.getsize(path) / (1024 * 1024)
        if size_mb > MAX_FILE_MB:
            QMessageBox.critical(
                self, self._s("err_title"),
                f"ファイルサイズが上限 ({MAX_FILE_MB}MB) を超えています: {size_mb:.1f}MB"
            )
            return

        # FIX-06: 前のスレッドを明示的に破棄
        if self.thread is not None:
            self.thread.deleteLater()
            self.thread = None

        self.btn_analyze.setEnabled(False)
        self.btn_select_file.setEnabled(False)
        self.btn_lang.setEnabled(False)  # 解析中は言語切り替え不可
        self.text_result.clear()
        self._set_status_style("processing")

        self.thread = AnalyzerThread(self.selected_file, self.api_key, self.lang)
        self.thread.progress_signal.connect(self.update_status)
        self.thread.finished_signal.connect(self.display_result)
        self.thread.error_signal.connect(self.display_error)
        self.thread.start()

    def update_status(self, msg):
        self.label_status.setText(msg)
        self._set_status_style("processing")

    def display_result(self, json_str):
        self.label_status.setText(self._s("status_done"))
        self._set_status_style("done")
        self.btn_analyze.setEnabled(True)
        self.btn_select_file.setEnabled(True)
        self.btn_lang.setEnabled(True)

        try:
            data = json.loads(json_str)
            self._render_result(data)
        except json.JSONDecodeError:
            self.text_result.setPlainText(self._s("err_json") + json_str)

    def display_error(self, error_msg):
        self.label_status.setText(self._s("status_error"))
        self._set_status_style("error")
        self.btn_analyze.setEnabled(True)
        self.btn_select_file.setEnabled(True)
        self.btn_lang.setEnabled(True)
        QMessageBox.critical(
            self, self._s("err_title"),
            self._s("err_body").format(msg=error_msg)
        )

    # ------------------------------------------
    # ステータスバースタイル
    # ------------------------------------------
    def _set_status_style(self, state):
        styles = {
            "idle":       "font-size: 13px; color: #666; background: #f0f0f0; border-radius: 4px; padding: 4px 10px;",
            "processing": "font-size: 13px; color: #1a73e8; background: #e8f0fe; border-radius: 4px; padding: 4px 10px;",
            "done":       "font-size: 13px; color: #188038; background: #e6f4ea; border-radius: 4px; padding: 4px 10px;",
            "error":      "font-size: 13px; color: #c5221f; background: #fce8e6; border-radius: 4px; padding: 4px 10px;",
        }
        self.label_status.setStyleSheet(styles.get(state, styles["idle"]))

    # ------------------------------------------
    # 結果レンダリング
    # ------------------------------------------
    def _render_result(self, data):
        s = STRINGS[self.lang]

        container = QWidget()
        container.setStyleSheet("background: white;")
        v = QVBoxLayout(container)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(12)

        # コア要素
        core_label = QLabel(s["core_label"])
        core_label.setFont(QFont(_FONT_FAMILY, 13, QFont.Weight.Bold))  # FIX-04
        v.addWidget(core_label)

        core_text = QLabel(str(data.get('original_analysis', s["core_fallback"])))
        core_text.setWordWrap(True)
        core_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        core_text.setStyleSheet(
            "font-size: 13px; color: #333; background: #f8f8f8;"
            "border: 1px solid #ddd; border-radius: 4px; padding: 8px;"
        )
        v.addWidget(core_text)

        # オリジナル曲の Suno Style Prompt
        orig_suno_prompt = data.get('original_suno_style_prompt', '')
        if orig_suno_prompt:
            orig_row = QHBoxLayout()
            orig_lbl = QLabel(s.get("original_suno_label", "▷ Original Suno Style Prompt"))
            orig_lbl.setStyleSheet(
                "font-size: 13px; font-weight: bold; color: #1a6b3a;"
            )
            orig_row.addWidget(orig_lbl)
            orig_row.addStretch()

            btn_orig_copy = QPushButton(s.get("btn_copy", "📋 Copy"))
            btn_orig_copy.setFixedSize(100, 30)
            btn_orig_copy.setStyleSheet(
                "QPushButton { font-size: 13px; background: #188038; color: white;"
                "border: none; border-radius: 4px; }"
                "QPushButton:hover { background: #0d5c2a; }"
                "QPushButton:pressed { background: #094020; }"
            )
            btn_orig_copy.clicked.connect(
                lambda checked, p=orig_suno_prompt, b=btn_orig_copy: self._copy_to_clipboard(p, b)
            )
            orig_row.addWidget(btn_orig_copy)
            v.addLayout(orig_row)

            orig_prompt_text = QLabel(orig_suno_prompt)
            orig_prompt_text.setWordWrap(True)
            orig_prompt_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            orig_prompt_text.setStyleSheet(
                "font-size: 13px; color: #222; background: #f0fff4;"
                "border: 1px solid #a8d5b5; border-radius: 4px; padding: 8px;"
            )
            v.addWidget(orig_prompt_text)

        # セパレータ
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #ccc;")
        v.addWidget(sep)

        header = QLabel(s["top3_header"])
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setFont(QFont(_FONT_FAMILY, 14, QFont.Weight.Bold))  # FIX-04
        header.setStyleSheet("color: #1a73e8; padding: 4px;")
        v.addWidget(header)

        # Top3 カード
        for item in data.get('recommendations', []):
            rank        = item.get('rank', '-')
            genre       = item.get('genre', s["genre_unknown"])
            reason      = item.get('reason', '')
            suno_prompt = item.get('suno_style_prompt', '')

            card = QWidget()
            card.setStyleSheet(
                "QWidget { background: #f0f4ff; border: 1px solid #c5d3f0; border-radius: 8px; }"
            )
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 10, 12, 10)
            cl.setSpacing(6)

            title_text = s["rank_title"].format(rank=rank, genre=genre)
            title = QLabel(title_text)
            title.setFont(QFont(_FONT_FAMILY, 13, QFont.Weight.Bold))  # FIX-04
            title.setStyleSheet("border: none; background: transparent; color: #1a3e8f;")
            cl.addWidget(title)

            reason_label = QLabel(s["reason_prefix"] + reason)
            reason_label.setWordWrap(True)
            reason_label.setStyleSheet("font-size: 13px; color: #444; border: none; background: transparent;")
            cl.addWidget(reason_label)

            tag_row = QHBoxLayout()
            tag_lbl = QLabel(s["suno_label"])
            tag_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #555; border: none; background: transparent;")
            tag_row.addWidget(tag_lbl)
            tag_row.addStretch()

            btn_copy = QPushButton(s["btn_copy"])
            btn_copy.setFixedSize(100, 30)
            btn_copy.setStyleSheet(
                "QPushButton { font-size: 13px; background: #1a73e8; color: white;"
                "border: none; border-radius: 4px; }"
                "QPushButton:hover { background: #1558c0; }"
                "QPushButton:pressed { background: #0d3d8c; }"
            )
            btn_copy.clicked.connect(
                lambda checked, p=suno_prompt, b=btn_copy: self._copy_to_clipboard(p, b)
            )
            tag_row.addWidget(btn_copy)
            cl.addLayout(tag_row)

            tag_text = QLabel(suno_prompt)
            tag_text.setWordWrap(True)
            tag_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            tag_text.setStyleSheet(
                "font-size: 13px; color: #222; background: #ffffff;"
                "border: 1px solid #c0cce8; border-radius: 4px; padding: 8px;"
            )
            cl.addWidget(tag_text)
            v.addWidget(card)

        v.addStretch()

        # QScrollArea に差し替え
        self.text_result.hide()
        if self._scroll_area:
            self.layout().removeWidget(self._scroll_area)
            self._scroll_area.deleteLater()

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setWidget(container)
        self._scroll_area.setStyleSheet(
            "QScrollArea { border: 1px solid #ddd; border-radius: 6px; background: white; }"
        )
        self.layout().addWidget(self._scroll_area)

    # ------------------------------------------
    # クリップボードコピー
    # ------------------------------------------
    def _copy_to_clipboard(self, text, btn):
        QApplication.clipboard().setText(text)
        s = STRINGS[self.lang]
        original_text  = btn.text()
        original_style = (
            "QPushButton { font-size: 13px; background: #1a73e8; color: white;"
            "border: none; border-radius: 4px; }"
            "QPushButton:hover { background: #1558c0; }"
        )
        btn.setText(s["btn_copied"])
        btn.setStyleSheet(
            "QPushButton { font-size: 13px; background: #188038; color: white;"
            "border: none; border-radius: 4px; }"
        )
        QTimer.singleShot(1500, lambda: (
            btn.setText(original_text),
            btn.setStyleSheet(original_style)
        ))


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = RemixAnalyzerApp()
    ex.show()
    sys.exit(app.exec())
