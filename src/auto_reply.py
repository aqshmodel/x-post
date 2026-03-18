"""
X投稿システム 自動リプライモジュール
60分間隔（7:00-23:00）でメンションをポーリングし、
Gemini LLMで返信テキストを生成して自動リプライする。
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import google.generativeai as genai

from src.config import get_account_dir, is_account_active, list_accounts, load_character
from src.utils import write_log
from src.x_client import fetch_mentions, reply_to_tweet, like_tweet, get_tweet_text


# --- 状態管理 ---

def _get_state_path(account_name: str) -> Path:
    return get_account_dir(account_name) / "logs" / "auto_reply_state.json"


def _load_state(account_name: str) -> dict:
    path = _get_state_path(account_name)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_mention_id": None, "replied_ids": []}


def _save_state(account_name: str, state: dict) -> None:
    path = _get_state_path(account_name)
    state["replied_ids"] = state.get("replied_ids", [])[-200:]
    state["updated_at"] = datetime.now().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# --- x_user_id 自動取得・保存 ---

def _ensure_user_id(account_name: str) -> Optional[str]:
    """x_user_idが未設定ならAPIで取得してconfig.jsonに自動保存する"""
    config_path = get_account_dir(account_name) / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    user_id = config.get("x_user_id", "")
    if user_id:
        return user_id

    # APIで取得
    from src.x_client import get_client
    try:
        client = get_client(account_name)
        me = client.get_me()
        if me.data:
            user_id = str(me.data.id)
            config["x_user_id"] = user_id
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            write_log(account_name, f"x_user_id を自動取得・保存: {user_id}")
            return user_id
    except Exception as e:
        write_log(account_name, f"x_user_id 取得失敗: {e}", level="ERROR")

    return None


# --- 元投稿の文脈取得 ---

def _get_original_context(account_name: str, mention: dict) -> str:
    """リプライの文脈（元の自分の投稿）を取得する"""
    conversation_id = mention.get("conversation_id")
    if not conversation_id:
        return ""

    # conversation_idの元ツイートを取得
    original_text = get_tweet_text(account_name, conversation_id)
    if original_text:
        return f"\n\n## 自分の元投稿（相手はこの投稿にリプライしている）\n{original_text}"
    return ""


# --- LLM返信生成 ---

def _generate_reply_text(
    account_name: str,
    mention_text: str,
    mention_author: str,
    character_md: str,
    original_context: str = "",
) -> Optional[str]:
    """Gemini LLMで返信テキストを生成（REST API経由）"""
    import urllib.request

    api_key = os.getenv("GEMINI_API_KEY")
    model_name = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")

    if not api_key:
        write_log(account_name, "GEMINI_API_KEY が未設定です", level="ERROR")
        return None

    prompt = f"""あなたはX（旧Twitter）で性格診断サービスを運営している人間です。
リプライに対して自然な返信を1つだけ作成してください。

## 最重要ルール（違反厳禁）
1. 相手が言っていないことには絶対に触れない。相手が悩んでいないなら励まさない。慰めない。
2. 相手のテンション・温度感に合わせる。軽いコメントには軽く返す。深い悩みには丁寧に返す。
3. 1-2文で十分。無理に長くしない。
4. 相手の@ユーザー名は書かない（Xが自動付与する）。
{original_context}

## 返信のトーン
- カジュアルだが知的。礼節ある話し方で丁寧。専門知識はちゃんとある人
- 絵文字・ハッシュタグ・「」・外部URLは使わない
- 「ご質問ありがとうございます」「共感します」等のテンプレ文は絶対禁止
- AIっぽさが出たら失格

## 返信パターンの例（参考）
相手「当たってる！」→ 「ですよね、○○型は〜な傾向があるのでピンとくる人多いです」程度でOK
相手「私もこれだった」→ 「仲間ですね。○○あるあるだと△△とかも心当たりありません？」程度
相手「質問なんですが〜」→ 質問に具体的に答える

## 相手のリプライ
@{mention_author}: {mention_text}

## 返信（テキストのみ。説明不要）:"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            reply_text = result["candidates"][0]["content"]["parts"][0]["text"].strip()

        # 先頭・末尾のクォートやマーカーを除去
        for ch in ['"', "'", "「", "」", "`"]:
            reply_text = reply_text.strip(ch)
        reply_text = reply_text.strip()

        if not reply_text:
            write_log(account_name, "生成テキストが空", level="WARN")
            return None

        # 長すぎる場合は切り捨て
        if len(reply_text) > 140:
            reply_text = reply_text[:137] + "..."

        write_log(account_name, f"返信テキスト生成: {reply_text[:50]}...")
        return reply_text

    except Exception as e:
        write_log(account_name, f"Gemini API エラー: {e}", level="ERROR")
        return None


# --- メイン処理 ---

def process_auto_replies(account_name: str) -> dict:
    """
    1つのアカウントの自動リプライ処理を実行
    Returns: {"checked": int, "replied": int, "liked": int, "skipped": int, "errors": int}
    """
    result = {"checked": 0, "replied": 0, "liked": 0, "skipped": 0, "errors": 0}

    # 稼働時間帯チェック（7:00-23:00 JST）
    now = datetime.now()
    if now.hour < 7 or now.hour >= 23:
        write_log(account_name, f"稼働時間外 ({now.hour}:00): スキップ")
        return result

    if not is_account_active(account_name):
        return result

    # character.md を読み込み
    character_md = load_character(account_name)
    if not character_md:
        write_log(account_name, "character.md が見つかりません", level="WARN")
        return result

    # x_user_id を確保
    my_user_id = _ensure_user_id(account_name)

    # 状態を読み込み
    state = _load_state(account_name)
    last_mention_id = state.get("last_mention_id")
    replied_ids = set(state.get("replied_ids", []))

    # メンション取得
    mentions = fetch_mentions(account_name, since_id=last_mention_id)
    result["checked"] = len(mentions)

    if not mentions:
        return result

    # 最新のIDを記録（処理前に更新して、次回取得時の起点にする）
    new_last_id = max(m["id"] for m in mentions)

    for i, mention in enumerate(mentions):
        mention_id = mention["id"]

        # 既に返信済みならスキップ
        if mention_id in replied_ids:
            result["skipped"] += 1
            continue

        # 自分のツイートは除外
        if my_user_id and mention["author_id"] == my_user_id:
            result["skipped"] += 1
            continue

        # === いいねを返す ===
        if like_tweet(account_name, mention_id):
            result["liked"] += 1

        # === 元投稿の文脈を取得 ===
        original_context = _get_original_context(account_name, mention)

        # === 返信テキスト生成 ===
        reply_text = _generate_reply_text(
            account_name,
            mention["text"],
            mention.get("author_username", ""),
            character_md,
            original_context,
        )

        if not reply_text:
            result["errors"] += 1
            replied_ids.add(mention_id)  # エラーでも既処理としてマーク
            continue

        # === リプライ投稿 ===
        reply_id = reply_to_tweet(account_name, mention_id, reply_text)
        if reply_id:
            result["replied"] += 1
            write_log(
                account_name,
                f"自動リプライ: @{mention.get('author_username', '?')} → {reply_text[:40]}...",
            )
        else:
            result["errors"] += 1

        replied_ids.add(mention_id)

        # === 連続投稿にならないよう遅延 ===
        if i < len(mentions) - 1:
            time.sleep(5)

    # 状態を保存
    state["last_mention_id"] = new_last_id
    state["replied_ids"] = list(replied_ids)
    _save_state(account_name, state)

    write_log(
        account_name,
        f"自動リプライ完了: checked={result['checked']}, replied={result['replied']}, "
        f"liked={result['liked']}, skipped={result['skipped']}, errors={result['errors']}",
    )
    return result


def run_auto_reply_job() -> None:
    """全アクティブアカウントの自動リプライを実行（スケジューラから呼ばれる）"""
    for account_name in list_accounts():
        try:
            config_path = get_account_dir(account_name) / "config.json"
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            if not config.get("auto_reply", {}).get("enabled", False):
                continue

            process_auto_replies(account_name)
        except Exception as e:
            write_log(account_name, f"自動リプライジョブ失敗: {e}", level="ERROR")
