import logging
from datetime import datetime
from time import perf_counter
from typing import Optional

from fastapi import Depends, FastAPI, Form, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from fastapi.responses import JSONResponse

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from . import auth, models
from .ai_workflow import get_ai_video_workflow
from .database import Base, SessionLocal, engine, get_db
from .logging_config import configure_logging

configure_logging()
logger = logging.getLogger("social_admin.app")

REQUEST_COUNT = Counter(
    "social_admin_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "social_admin_request_latency_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)

app = FastAPI(title="Social Admin")
app.add_middleware(SessionMiddleware, secret_key="super-secret-session-key")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start_time = perf_counter()
    response: Response = await call_next(request)
    elapsed = perf_counter() - start_time
    path = request.url.path
    method = request.method
    status = response.status_code

    REQUEST_COUNT.labels(method=method, path=path, status=status).inc()
    REQUEST_LATENCY.labels(method=method, path=path).observe(elapsed)
    logger.debug(
        "Processed request",
        extra={
            "method": method,
            "path": path,
            "status": status,
            "duration": elapsed,
        },
    )
    return response


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        auth.ensure_default_admin(db)
        logger.info("Startup complete and default admin ensured.")
    finally:
        db.close()


@app.get("/login")
async def login_form(request: Request):
    user = request.session.get("user_id")
    if user:
        logger.debug("Authenticated user attempted to access login form", extra={"user_id": user})
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    username = form.get("username", "").strip()
    password = form.get("password", "")

    user = db.query(models.AdminUser).filter_by(username=username).first()
    if not user or not auth.verify_password(password, user.password_hash):
        logger.warning(
            "Failed login attempt",
            extra={"username": username, "ip": request.client.host if request.client else None},
        )
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "نام کاربری یا رمز عبور نادرست است."},
            status_code=400,
        )

    request.session["user_id"] = user.id
    logger.info(
        "User logged in",
        extra={"user_id": user.id, "username": username, "ip": request.client.host if request.client else None},
    )
    return RedirectResponse(url="/", status_code=302)


@app.post("/logout")
async def logout(request: Request):
    user_id = request.session.get("user_id")
    request.session.clear()
    if user_id:
        logger.info("User logged out", extra={"user_id": user_id})
    return RedirectResponse(url="/login", status_code=302)


@app.get("/")
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user = auth.get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    accounts = db.query(models.SocialAccount).order_by(models.SocialAccount.created_at.desc()).all()
    scheduled_posts = (
        db.query(models.ScheduledPost)
        .order_by(models.ScheduledPost.scheduled_time.asc())
        .limit(10)
        .all()
    )
    tokens = db.query(models.ServiceToken).order_by(models.ServiceToken.created_at.desc()).all()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "accounts": accounts,
            "scheduled_posts": scheduled_posts,
            "tokens": tokens,
            "active_page": "dashboard",
        },
    )


@app.get("/metrics")
async def metrics() -> Response:
    """Expose Prometheus metrics for scraping."""

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/settings")
async def settings(request: Request, db: Session = Depends(get_db)):
    user = auth.get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    tokens = db.query(models.ServiceToken).all()
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
            "tokens": tokens,
            "active_page": "settings",
        },
    )


@app.get("/ai/video-workflow", response_class=JSONResponse)
async def ai_video_workflow() -> JSONResponse:
    """Return a curated list of AI video tools and workflow steps."""

    logger.debug("AI video workflow requested")
    return JSONResponse(get_ai_video_workflow())


@app.post("/settings")
async def create_or_update_token(
    request: Request,
    name: str = Form(...),
    key: str = Form(...),
    value: str = Form(...),
    db: Session = Depends(get_db),
):
    user = auth.get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    token = db.query(models.ServiceToken).filter_by(key=key).first()
    if token:
        token.name = name
        token.value = value
        logger.info(
            "Service token updated",
            extra={"user_id": user.id, "token_id": token.id, "key": key},
        )
    else:
        token = models.ServiceToken(name=name, key=key, value=value)
        db.add(token)
        logger.info(
            "Service token created",
            extra={"user_id": user.id, "key": key},
        )
    db.commit()
    return RedirectResponse(url="/settings", status_code=302)


@app.post("/settings/delete")
async def delete_token(request: Request, token_id: int = Form(...), db: Session = Depends(get_db)):
    user = auth.get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    token = db.get(models.ServiceToken, token_id)
    if token:
        db.delete(token)
        db.commit()
        logger.info(
            "Service token deleted",
            extra={"user_id": user.id, "token_id": token_id},
        )
    return RedirectResponse(url="/settings", status_code=302)


@app.get("/accounts")
async def list_accounts(request: Request, db: Session = Depends(get_db)):
    user = auth.get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    accounts = db.query(models.SocialAccount).order_by(models.SocialAccount.created_at.desc()).all()
    return templates.TemplateResponse(
        "accounts.html",
        {
            "request": request,
            "user": user,
            "accounts": accounts,
            "active_page": "accounts",
        },
    )


@app.get("/accounts/new")
async def new_account(request: Request, db: Session = Depends(get_db)):
    user = auth.get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "account_form.html",
        {
            "request": request,
            "user": user,
            "account": None,
            "active_page": "accounts",
        },
    )


@app.get("/accounts/{account_id}")
async def edit_account(account_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    account = db.get(models.SocialAccount, account_id)
    if not account:
        return RedirectResponse(url="/accounts", status_code=302)

    return templates.TemplateResponse(
        "account_form.html",
        {
            "request": request,
            "user": user,
            "account": account,
            "active_page": "accounts",
        },
    )


@app.post("/accounts")
async def save_account(
    request: Request,
    platform: str = Form(...),
    display_name: str = Form(...),
    page_id: Optional[str] = Form(None),
    oauth_token: Optional[str] = Form(None),
    youtube_channel_id: Optional[str] = Form(None),
    telegram_chat_id: Optional[str] = Form(None),
    account_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    user = auth.get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if account_id:
        account = db.get(models.SocialAccount, int(account_id))
        if not account:
            logger.warning(
                "Attempted to update non-existent account",
                extra={"user_id": user.id, "account_id": account_id},
            )
            return RedirectResponse(url="/accounts", status_code=302)
    else:
        account = models.SocialAccount(platform=platform, display_name=display_name)
        db.add(account)
        logger.info(
            "Creating new account",
            extra={"user_id": user.id, "platform": platform},
        )

    def _clean(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None

    account.platform = platform
    account.display_name = display_name.strip()
    account.page_id = _clean(page_id)
    account.oauth_token = _clean(oauth_token)
    account.youtube_channel_id = _clean(youtube_channel_id)
    account.telegram_chat_id = _clean(telegram_chat_id)

    db.commit()
    logger.info(
        "Account saved",
        extra={"user_id": user.id, "account_id": account.id, "platform": account.platform},
    )
    return RedirectResponse(url="/accounts", status_code=302)


@app.post("/accounts/delete")
async def delete_account(request: Request, account_id: int = Form(...), db: Session = Depends(get_db)):
    user = auth.get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    account = db.get(models.SocialAccount, account_id)
    if account:
        db.delete(account)
        db.commit()
        logger.info(
            "Account deleted",
            extra={"user_id": user.id, "account_id": account_id, "platform": account.platform},
        )
    return RedirectResponse(url="/accounts", status_code=302)


@app.get("/scheduler")
async def scheduler(request: Request, db: Session = Depends(get_db)):
    user = auth.get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    accounts = db.query(models.SocialAccount).all()
    posts = db.query(models.ScheduledPost).order_by(models.ScheduledPost.scheduled_time.desc()).all()
    return templates.TemplateResponse(
        "scheduler.html",
        {
            "request": request,
            "user": user,
            "accounts": accounts,
            "posts": posts,
            "active_page": "scheduler",
        },
    )


@app.post("/scheduler")
async def create_schedule(
    request: Request,
    account_id: int = Form(...),
    title: str = Form(...),
    content: Optional[str] = Form(None),
    video_url: Optional[str] = Form(None),
    scheduled_time: str = Form(...),
    db: Session = Depends(get_db),
):
    user = auth.get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    raw_time = scheduled_time.strip()
    if raw_time.endswith("Z"):
        raw_time = raw_time[:-1]
    try:
        schedule_dt = datetime.fromisoformat(raw_time)
    except ValueError:
        accounts = db.query(models.SocialAccount).all()
        posts = (
            db.query(models.ScheduledPost)
            .order_by(models.ScheduledPost.scheduled_time.desc())
            .all()
        )
        logger.warning(
            "Invalid schedule timestamp provided",
            extra={"user_id": user.id, "account_id": account_id, "value": scheduled_time},
        )
        return templates.TemplateResponse(
            "scheduler.html",
            {
                "request": request,
                "user": user,
                "accounts": accounts,
                "posts": posts,
                "error": "فرمت تاریخ/زمان نامعتبر است.",
                "active_page": "scheduler",
            },
            status_code=400,
        )
    text_content = None
    if content:
        text_content = content.strip() or None

    video_link = None
    if video_url:
        video_link = video_url.strip() or None

    post = models.ScheduledPost(
        account_id=account_id,
        title=title,
        content=text_content,
        video_url=video_link,
        scheduled_time=schedule_dt,
    )
    db.add(post)
    db.commit()
    logger.info(
        "Post scheduled",
        extra={
            "user_id": user.id,
            "account_id": account_id,
            "post_id": post.id,
            "scheduled_time": schedule_dt.isoformat(),
        },
    )
    return RedirectResponse(url="/scheduler", status_code=302)


@app.post("/scheduler/delete")
async def delete_schedule(request: Request, post_id: int = Form(...), db: Session = Depends(get_db)):
    user = auth.get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    post = db.get(models.ScheduledPost, post_id)
    if post:
        db.delete(post)
        db.commit()
        logger.info(
            "Scheduled post deleted",
            extra={"user_id": user.id, "post_id": post_id, "account_id": post.account_id},
        )
    return RedirectResponse(url="/scheduler", status_code=302)
