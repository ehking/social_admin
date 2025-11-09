# social_admin

این مخزن شامل پیاده‌سازی اولیه پنل ادمین و مستندات سامانه «دستیار تولید و انتشار محتوای خودکار» است. برای جزئیات ویژگی‌ها به [docs/project_spec.md](docs/project_spec.md) مراجعه کنید.

## اجرای پنل ادمین (FastAPI)

1. ایجاد محیط مجازی و نصب پیش‌نیازها:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. اجرای سرور توسعه:

   ```bash
   uvicorn app.main:app --reload
   ```

3. دسترسی به پنل از طریق مرورگر در آدرس [http://localhost:8000](http://localhost:8000).

- نام کاربری پیش‌فرض: `admin`
- رمز عبور پیش‌فرض: `admin123`

> رابط کاربری به‌صورت کامل راست‌چین (RTL) طراحی شده و از زبان فارسی پشتیبانی می‌کند.
