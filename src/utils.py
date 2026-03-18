"""
X投稿システム ユーティリティ
仕様: docs/仕様/04_投稿ワークフロー.md
"""

import json
import re
import shutil
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image

from src.config import get_account_dir


def count_characters(text: str) -> int:
    """
    X準拠の文字数カウント（weighted）
    ルール（2026年3月時点）:
    - 全角文字（日本語等）: 2ウェイト
    - 半角文字（ASCII英数字等）: 1ウェイト
    - URL: 23文字固定（=23ウェイト）
    - 絵文字: 2ウェイト
    - 上限: 280ウェイト（= 日本語140文字 or 半角280文字）
    """
    # NFC正規化
    normalized = unicodedata.normalize("NFC", text)

    # URLを検出して置換（1URLあたり23ウェイト）
    url_pattern = re.compile(r"https?://\S+")
    urls = url_pattern.findall(normalized)
    url_weight = len(urls) * 23
    for url in urls:
        normalized = normalized.replace(url, "", 1)

    weight = 0
    i = 0
    while i < len(normalized):
        char = normalized[i]

        # ZWJ シーケンス（複合絵文字）をスキップ
        if i + 1 < len(normalized) and normalized[i + 1] == "\u200d":
            weight += 2  # 複合絵文字全体で2ウェイト
            # ZWJ シーケンスの終端まで進む
            while i + 1 < len(normalized) and normalized[i + 1] == "\u200d":
                i += 2
            i += 1
            continue

        # サロゲートペア/絵文字
        if ord(char) > 0xFFFF or unicodedata.category(char).startswith("So"):
            weight += 2
        # 全角判定: CJK統合漢字、ひらがな、カタカナ、全角記号等
        elif _is_fullwidth(char):
            weight += 2
        else:
            weight += 1
        i += 1

    return weight + url_weight


def _is_fullwidth(char: str) -> bool:
    """全角文字かどうかを判定（X APIのルールに準拠）"""
    cp = ord(char)
    # East Asian Width が F(Fullwidth) or W(Wide) の文字
    ea = unicodedata.east_asian_width(char)
    if ea in ("F", "W"):
        return True
    # ひらがな・カタカナ・CJK統合漢字・全角記号
    if (0x3000 <= cp <= 0x303F or   # CJK記号・句読点
        0x3040 <= cp <= 0x309F or   # ひらがな
        0x30A0 <= cp <= 0x30FF or   # カタカナ
        0x4E00 <= cp <= 0x9FFF or   # CJK統合漢字
        0xFF00 <= cp <= 0xFFEF):    # 全角ASCII・半角カナ
        return True
    return False


def generate_post_id(slug: str) -> str:
    """YYYY-MM-DD_{slug} 形式のIDを生成"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    # スラグのサニタイズ
    safe_slug = re.sub(r"[^\w\-]", "-", slug.lower().strip())
    safe_slug = re.sub(r"-+", "-", safe_slug).strip("-")
    return f"{date_str}_{safe_slug}"


def save_post_json(account_name: str, status_dir: str, post_data: dict) -> Path:
    """ポストJSONをファイルに保存"""
    dir_path = get_account_dir(account_name) / status_dir
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / f"{post_data['id']}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(post_data, f, ensure_ascii=False, indent=2, default=str)
    return file_path


def load_post_json(account_name: str, status_dir: str, post_id: str) -> dict:
    """ポストJSONをファイルから読み込み"""
    file_path = get_account_dir(account_name) / status_dir / f"{post_id}.json"
    if not file_path.exists():
        raise FileNotFoundError(f"ポストが見つかりません: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_posts(account_name: str, status_dir: str) -> list[dict]:
    """指定ディレクトリ内のポストJSON一覧を取得"""
    dir_path = get_account_dir(account_name) / status_dir
    if not dir_path.exists():
        return []
    posts = []
    for file_path in sorted(dir_path.glob("*.json"), reverse=True):
        with open(file_path, "r", encoding="utf-8") as f:
            posts.append(json.load(f))
    return posts


def move_post(account_name: str, post_id: str, from_dir: str, to_dir: str) -> Path:
    """ポストJSONファイルをディレクトリ間で移動"""
    src = get_account_dir(account_name) / from_dir / f"{post_id}.json"
    dst_dir = get_account_dir(account_name) / to_dir
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{post_id}.json"
    shutil.move(str(src), str(dst))
    return dst


def convert_to_jpeg(input_path: str, output_path: str, quality: int = 90) -> str:
    """画像をJPEGに変換（WebP→JPEG等）"""
    with Image.open(input_path) as img:
        # RGBA → RGB 変換（JPEG はアルファチャンネル非対応）
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(output_path, "JPEG", quality=quality)
    return output_path


def generate_image_filename(post_id: str, index: int, ext: str = "jpg") -> str:
    """画像ファイル名を生成: {post_id}_{連番}.{ext}"""
    return f"{post_id}_{index}.{ext}"


def write_log(account_name: str, message: str, level: str = "INFO") -> None:
    """アカウントのログファイルに追記"""
    log_dir = get_account_dir(account_name) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] [{level}] {message}\n")


def split_into_thread(text: str, max_weight: int = 280) -> list[str]:
    """
    テキストを max_weight 以内のチャンクに分割する。
    分割優先順位: 改行 > 句点「。」> 読点「、」> スペース > 強制分割
    280ウェイト以内ならそのまま1要素リストで返す。
    """
    text = text.strip()
    if not text:
        return []
    if count_characters(text) <= max_weight:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        remaining = remaining.strip()
        if not remaining:
            break
        if count_characters(remaining) <= max_weight:
            chunks.append(remaining)
            break

        # max_weight に収まる最長の部分を探す
        best_pos = _find_split_position(remaining, max_weight)
        chunk = remaining[:best_pos].rstrip()
        if not chunk:
            # 1文字も入らないケース（ありえないが安全策）
            chunk = remaining[:1]
            best_pos = 1
        chunks.append(chunk)
        remaining = remaining[best_pos:]

    return chunks


def _find_split_position(text: str, max_weight: int) -> int:
    """
    max_weight 以内に収まる最良の分割位置を返す。
    分割優先順位: 改行 > 句点 > 読点 > スペース > 強制カット
    """
    # まず max_weight に収まる最大の文字位置を二分探索で見つける
    lo, hi = 1, len(text)
    max_pos = 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if count_characters(text[:mid]) <= max_weight:
            max_pos = mid
            lo = mid + 1
        else:
            hi = mid - 1

    # max_pos の範囲内で最適な分割点を探す
    search_range = text[:max_pos]

    # 優先1: 改行
    pos = search_range.rfind("\n")
    if pos > 0:
        return pos + 1  # 改行の直後で分割

    # 優先2: 句点「。」
    pos = search_range.rfind("。")
    if pos > 0:
        return pos + 1

    # 優先3: 読点「、」
    pos = search_range.rfind("、")
    if pos > 0:
        return pos + 1

    # 優先4: スペース
    pos = search_range.rfind(" ")
    if pos > 0:
        return pos + 1

    # 優先5: 強制カット
    return max_pos
