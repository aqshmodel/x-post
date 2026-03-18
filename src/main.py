"""
X投稿システム FastAPIサーバー
仕様: docs/仕様/05_予約投稿.md, 08_管理UI.md
"""

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config import (
    BASE_DIR,
    STATIC_DIR,
    TEMPLATES_DIR,
    list_accounts,
    load_account,
    is_account_active,
    get_account_dir,
)
from src.models import (
    Post,
    PostStatus,
    PublishRequest,
    ScheduleRequest,
    ApiPricing,
)
from src.utils import (
    count_characters,
    generate_post_id,
    list_posts,
    load_post_json,
    save_post_json,
    move_post,
    write_log,
)
from src.scheduler import (
    init_scheduler,
    recover_jobs,
    schedule_post,
    cancel_scheduled_post,
    retry_failed_post,
    schedule_monthly_archive,
    schedule_auto_reply,
)
from src.analytics import (
    fetch_and_update,
    update_daily_summary,
    update_monthly_summary,
    load_monthly_archive,
    list_monthly_archives,
)


# --- ライフサイクル ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """サーバー起動/終了処理"""
    # 起動
    sched = init_scheduler()
    results = recover_jobs()
    schedule_monthly_archive()
    schedule_auto_reply()
    print(f"[Scheduler] ジョブ復旧: 登録={results['registered']}, 即時実行={results['executed']}, 失敗={results['failed']}")
    yield
    # 終了
    sched.shutdown()


app = FastAPI(title="X投稿管理システム", version="1.0.0", lifespan=lifespan)

# 静的ファイル & テンプレート
STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ============================
# ヘルスチェック
# ============================

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# ============================
# アカウント管理 API
# ============================

@app.get("/api/accounts")
async def api_list_accounts():
    accounts = []
    for name in list_accounts():
        try:
            acc = load_account(name)
            posted = list_posts(name, "posted")
            accounts.append({
                "account_name": acc.account_name,
                "display_name": acc.display_name,
                "x_username": acc.x_username,
                "active": acc.active,
                "total_posts": len(posted),
            })
        except Exception:
            pass
    return accounts


@app.get("/api/accounts/{name}")
async def api_get_account(name: str):
    try:
        acc = load_account(name)
        return acc.model_dump()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"アカウント '{name}' が見つかりません")


# ============================
# 投稿管理 API
# ============================

def _check_active_or_403(account_name: str):
    """active: false なら 403"""
    if not is_account_active(account_name):
        raise HTTPException(
            status_code=403,
            detail=f"アカウント '{account_name}' は無効化されています (active: false)"
        )


@app.post("/api/posts/draft")
async def api_create_draft(req: PublishRequest):
    """下書き保存"""
    try:
        load_account(req.account)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"アカウント '{req.account}' が見つかりません")

    # 文字数チェック
    char_count = count_characters(req.text)
    if char_count > 280:
        raise HTTPException(status_code=400, detail=f"文字数超過: {char_count}/280文字")

    # ID生成
    slug = req.text[:20].replace(" ", "-").replace("\n", "-")
    post_id = generate_post_id(slug)

    post = Post(
        id=post_id,
        account=req.account,
        text=req.text,
        media=req.media,
        status=PostStatus.DRAFT,
    )

    save_post_json(req.account, "drafts", post.model_dump())
    write_log(req.account, f"下書き保存: {post_id}")
    return post.model_dump()


@app.post("/api/posts/publish")
async def api_publish(req: PublishRequest):
    """即時投稿"""
    _check_active_or_403(req.account)

    char_count = count_characters(req.text)
    if char_count > 280:
        raise HTTPException(status_code=400, detail=f"文字数超過: {char_count}/280文字")

    slug = req.text[:20].replace(" ", "-").replace("\n", "-")
    post_id = generate_post_id(slug)

    post = Post(
        id=post_id,
        account=req.account,
        text=req.text,
        media=req.media,
        status=PostStatus.DRAFT,
    )

    try:
        from src.x_client import publish_post
        result = publish_post(req.account, post)
        return result.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/posts/schedule")
async def api_schedule(req: ScheduleRequest):
    """予約投稿登録"""
    _check_active_or_403(req.account)

    char_count = count_characters(req.text)
    if char_count > 280:
        raise HTTPException(status_code=400, detail=f"文字数超過: {char_count}/280文字")

    # タイムゾーン対応の比較
    now = datetime.now(req.scheduled_at.tzinfo) if req.scheduled_at.tzinfo else datetime.now()
    if req.scheduled_at <= now:
        raise HTTPException(status_code=400, detail="予約時刻は未来でなければなりません")

    slug = req.text[:20].replace(" ", "-").replace("\n", "-")
    post_id = generate_post_id(slug)

    post = Post(
        id=post_id,
        account=req.account,
        text=req.text,
        media=req.media,
        status=PostStatus.SCHEDULED,
        scheduled_at=req.scheduled_at,
    )

    save_post_json(req.account, "scheduled", post.model_dump())
    job_id = schedule_post(req.account, post)
    write_log(req.account, f"予約投稿登録: {post_id} → {req.scheduled_at}")
    return {"post_id": post_id, "job_id": job_id, "scheduled_at": req.scheduled_at.isoformat()}


@app.get("/api/posts/drafts")
async def api_list_drafts(account: str = Query(...)):
    return list_posts(account, "drafts")


@app.get("/api/posts/scheduled")
async def api_list_scheduled(account: str = Query(...)):
    return list_posts(account, "scheduled")


@app.get("/api/posts/posted")
async def api_list_posted(account: str = Query(...)):
    return list_posts(account, "posted")


@app.delete("/api/posts/scheduled/{post_id}")
async def api_cancel_scheduled(post_id: str, account: str = Query(...)):
    """予約キャンセル（draft に戻す）"""
    try:
        cancel_scheduled_post(account, post_id)
        return {"status": "cancelled", "post_id": post_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/posts/retry/{post_id}")
async def api_retry_post(post_id: str, account: str = Query(...)):
    """失敗投稿のリトライ"""
    _check_active_or_403(account)

    try:
        from src.x_client import publish_post
        post_data = load_post_json(account, "scheduled", post_id)
        post = Post(**post_data)
        result = publish_post(account, post)
        # scheduled/ のファイルを削除
        scheduled_file = get_account_dir(account) / "scheduled" / f"{post_id}.json"
        if scheduled_file.exists():
            scheduled_file.unlink()
        return result.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/posts/{status_dir}/{post_id}")
async def api_update_post(status_dir: str, post_id: str, request: Request, account: str = Query(...)):
    """投稿のテキスト・予約時刻を編集"""
    body = await request.json()
    try:
        post_data = load_post_json(account, status_dir, post_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="ポストが見つかりません")

    # テキスト更新
    if "text" in body:
        char_count = count_characters(body["text"])
        if char_count > 280:
            raise HTTPException(status_code=400, detail=f"文字数超過: {char_count}/280文字")
        post_data["text"] = body["text"]

    # 予約時刻更新
    if "scheduled_at" in body and body["scheduled_at"]:
        post_data["scheduled_at"] = body["scheduled_at"]
        # スケジューラのジョブも再登録
        if post_data.get("status") == "scheduled":
            post = Post(**post_data)
            schedule_post(account, post)

    post_data["updated_at"] = datetime.now().isoformat()
    save_post_json(account, status_dir, post_data)
    write_log(account, f"投稿編集: {post_id}")
    return {"status": "updated", "post_id": post_id}


# ============================
# 分析 API
# ============================

@app.get("/api/analytics/{account}")
async def api_analytics_summary(account: str):
    """アカウントの当月サマリ"""
    try:
        summary = update_monthly_summary(account)
        return summary.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analytics/{account}/{post_id}")
async def api_analytics_post(account: str, post_id: str):
    """ポスト別分析"""
    try:
        post_data = load_post_json(account, "posted", post_id)
        return post_data.get("analytics", {})
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="ポストが見つかりません")


@app.post("/api/analytics/{account}/fetch")
async def api_analytics_fetch(account: str, post_id: Optional[str] = None):
    """分析データ手動取得（直近10投稿）"""
    if post_id:
        result = fetch_and_update(account, post_id)
        return {"updated": 1, "post_id": post_id}
    else:
        # 直近10投稿のみ分析を更新（API費用節約）
        posted = list_posts(account, "posted")
        # x_post_id がある投稿のみ、新しい順にソート
        with_id = [p for p in posted if p.get("x_post_id")]
        with_id.sort(key=lambda p: p.get("posted_at", ""), reverse=True)
        recent = with_id[:10]

        updated = 0
        errors = []
        for p in recent:
            try:
                fetch_and_update(account, p["id"])
                updated += 1
            except Exception as e:
                errors.append({"post_id": p["id"], "error": str(e)})
        return {"updated": updated, "total": len(recent), "errors": errors}


@app.get("/api/cost-history/{account}")
async def api_cost_history(account: str):
    """月別コスト履歴"""
    months = list_monthly_archives(account)
    history = []
    for m in months:
        data = load_monthly_archive(account, m)
        if data:
            history.append({
                "month": m,
                "total_posts": data.get("total_posts", 0),
                "api_cost": data.get("api_cost", {}),
            })
    # 当月を追加
    try:
        current = update_monthly_summary(account)
        history.insert(0, {
            "month": current.month,
            "total_posts": current.total_posts,
            "api_cost": current.api_cost.model_dump(),
            "current": True,
        })
    except Exception:
        pass
    return history


# ============================
# 管理 UI ルート
# ============================

@app.get("/", response_class=HTMLResponse)
async def ui_dashboard(request: Request):
    """ダッシュボード"""
    all_accounts = list_accounts()
    accounts = []
    for name in all_accounts:
        try:
            acc = load_account(name)
            posted = list_posts(name, "posted")
            scheduled = list_posts(name, "scheduled")
            accounts.append({
                "account": acc,
                "total_posts": len(posted),
                "scheduled_count": len(scheduled),
                "recent_posts": posted[:3],
            })
        except Exception:
            pass

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "accounts": accounts,
        "accounts_list": all_accounts,
        "current_page": "dashboard",
        "current_account": all_accounts[0] if all_accounts else None,
    })


@app.get("/ui/scheduled", response_class=HTMLResponse)
async def ui_scheduled(request: Request, account: str = Query(...)):
    """予約一覧ページ"""
    posts = list_posts(account, "scheduled")
    # 予約日時で昇順ソート（T/スペース混在を正規化）
    posts.sort(key=lambda p: (p.get("scheduled_at", "") or "").replace("T", " ")[:16])
    acc = load_account(account)
    return templates.TemplateResponse("posts_scheduled.html", {
        "request": request,
        "account": acc,
        "posts": posts,
        "accounts_list": list_accounts(),
        "current_page": "scheduled",
        "current_account": account,
    })


@app.get("/ui/post/{status_dir}/{post_id}", response_class=HTMLResponse)
async def ui_post_edit(request: Request, status_dir: str, post_id: str, account: str = Query(...)):
    """投稿詳細・編集ページ"""
    try:
        post_data = load_post_json(account, status_dir, post_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="ポストが見つかりません")
    acc = load_account(account)
    return templates.TemplateResponse("post_edit.html", {
        "request": request,
        "account": acc,
        "post": post_data,
        "accounts_list": list_accounts(),
        "current_page": "scheduled",
        "current_account": account,
    })


@app.get("/ui/history", response_class=HTMLResponse)
async def ui_history(request: Request, account: str = Query(...)):
    """投稿履歴ページ"""
    posts = list_posts(account, "posted")
    # 投稿日時で降順ソート（新しい投稿が上）
    posts.sort(key=lambda p: p.get("posted_at", "") or "", reverse=True)
    acc = load_account(account)
    return templates.TemplateResponse("posts_history.html", {
        "request": request,
        "account": acc,
        "posts": posts,
        "accounts_list": list_accounts(),
        "current_page": "history",
        "current_account": account,
    })


@app.get("/ui/analytics", response_class=HTMLResponse)
async def ui_analytics(request: Request, account: str = Query(...)):
    """分析ページ"""
    acc = load_account(account)
    summary = update_monthly_summary(account)
    return templates.TemplateResponse("analytics.html", {
        "request": request,
        "account": acc,
        "summary": summary.model_dump(),
        "accounts_list": list_accounts(),
        "current_page": "analytics",
        "current_account": account,
    })


@app.get("/ui/cost-history", response_class=HTMLResponse)
async def ui_cost_history(request: Request, account: str = Query(...)):
    """コスト履歴ページ"""
    acc = load_account(account)
    months = list_monthly_archives(account)
    archives = []
    for m in months:
        data = load_monthly_archive(account, m)
        if data:
            archives.append(data)
    current = update_monthly_summary(account)
    return templates.TemplateResponse("cost_history.html", {
        "request": request,
        "account": acc,
        "current_summary": current.model_dump(),
        "archives": archives,
        "accounts_list": list_accounts(),
        "current_page": "cost-history",
        "current_account": account,
    })
