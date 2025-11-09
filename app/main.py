from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import auth, models
from .database import Base, SessionLocal, engine, get_db

app = FastAPI(title="Social Admin")
app.add_middleware(SessionMiddleware, secret_key="super-secret-session-key")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        auth.ensure_default_admin(db)
    finally:
        db.close()


@app.get("/login")
async def login_form(request: Request):
    user = request.session.get("user_id")
    if user:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    username = form.get("username", "").strip()
    password = form.get("password", "")

    user = db.query(models.AdminUser).filter_by(username=username).first()
    if not user or not auth.verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "نام کاربری یا رمز عبور نادرست است."},
            status_code=400,
        )

    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=302)


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
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
        },
    )


@app.get("/settings")
async def settings(request: Request, db: Session = Depends(get_db)):
    user = auth.get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    tokens = db.query(models.ServiceToken).all()
    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "user": user, "tokens": tokens},
    )


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
    else:
        token = models.ServiceToken(name=name, key=key, value=value)
        db.add(token)
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
    return RedirectResponse(url="/settings", status_code=302)


@app.get("/accounts")
async def list_accounts(request: Request, db: Session = Depends(get_db)):
    user = auth.get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    accounts = db.query(models.SocialAccount).order_by(models.SocialAccount.created_at.desc()).all()
    return templates.TemplateResponse(
        "accounts.html",
        {"request": request, "user": user, "accounts": accounts},
    )


@app.get("/accounts/new")
async def new_account(request: Request, db: Session = Depends(get_db)):
    user = auth.get_logged_in_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "account_form.html",
        {"request": request, "user": user, "account": None},
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
        {"request": request, "user": user, "account": account},
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
            return RedirectResponse(url="/accounts", status_code=302)
    else:
        account = models.SocialAccount(platform=platform, display_name=display_name)
        db.add(account)

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
        return templates.TemplateResponse(
            "scheduler.html",
            {
                "request": request,
                "user": user,
                "accounts": accounts,
                "posts": posts,
                "error": "فرمت تاریخ/زمان نامعتبر است.",
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
    return RedirectResponse(url="/scheduler", status_code=302)
