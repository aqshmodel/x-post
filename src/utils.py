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
    X準拠の文字数カウント
    - Unicode NFC正規化後にカウント
    - URL: 23文字固定
    - 絵文字: 2文字
    - その他: 1文字
    """
    # NFC正規化
    normalized = unicodedata.normalize("NFC", text)

    # URLを検出して23文字固定に置換
    url_pattern = re.compile(r"https?://\S+")
    urls = url_pattern.findall(normalized)
    for url in urls:
        normalized = normalized.replace(url, "X" * 23, 1)

    count = 0
    i = 0
    while i < len(normalized):
        char = normalized[i]
        # サロゲートペア（絵文字等）の検出
        if ord(char) > 0xFFFF or unicodedata.category(char).startswith("So"):
            count += 2
        else:
            count += 1
        # ZWJ シーケンス（複合絵文字）をスキップ
        if i + 1 < len(normalized) and normalized[i + 1] == "\u200d":
            i += 2  # ZWJ + 次の文字をスキップ
            continue
        i += 1

    return count


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
