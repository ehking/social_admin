"""Presenter that prepares data for the documentation view."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.backend import models


@dataclass(slots=True)
class DocumentationPresenter:
    """Collect structured documentation content for rendering."""

    templates: Jinja2Templates

    def _build_sections(self) -> List[Dict[str, Any]]:
        return [
            {
                "title": "شروع سریع",
                "description": "مراحل اصلی راه‌اندازی سامانه از نصب تا زمان‌بندی انتشار.",
                "entries": [
                    {
                        "title": "پیکربندی توکن‌ها",
                        "content": "از منوی تنظیمات سرویس‌ها، کلیدهای OpenAI، شبکه‌های اجتماعی و سرویس‌های رسانه‌ای را ثبت کنید.",
                    },
                    {
                        "title": "افزودن اکانت‌ها",
                        "content": "در صفحه مدیریت اکانت‌ها اطلاعات احراز هویت هر پلتفرم را وارد کرده و دسترسی لازم را تأیید کنید.",
                    },
                    {
                        "title": "ایجاد صف انتشار",
                        "content": "در برنامه‌ریز انتشار، پست‌ها یا سناریوهای ویدیویی را به همراه زمان‌بندی و اولویت تعریف کنید.",
                    },
                ],
            },
            {
                "title": "اتوماسیون تولید محتوا",
                "description": "چگونگی استفاده از موتور سناریو و خط لوله ویدیویی.",
                "entries": [
                    {
                        "title": "تعریف سناریو",
                        "content": "سناریوهای JSON/YAML می‌توانند ترتیب صحنه‌ها، افکت‌ها و قوانین انتخاب رسانه را تعیین کنند.",
                    },
                    {
                        "title": "ترکیب محتوا",
                        "content": "سامانه متن خلاصه‌شده، صدا، B-roll و واترمارک Benita Music را به‌صورت خودکار ادغام می‌کند.",
                    },
                    {
                        "title": "پشتیبانی چندفرمتی",
                        "content": "خروجی در نسبت‌های 9:16، افقی و سایر قالب‌ها برای اینستاگرام، تیک‌تاک و یوتیوب تولید می‌شود.",
                    },
                ],
            },
            {
                "title": "پایش و امنیت",
                "description": "نمای کلی از امکانات مانیتورینگ و سیاست‌های امنیتی.",
                "entries": [
                    {
                        "title": "لاگ‌ها و متریک‌ها",
                        "content": "از طریق داشبورد وضعیت اجرا، خطاها و شمارنده‌های Prometheus را زیر نظر داشته باشید.",
                    },
                    {
                        "title": "مدیریت دسترسی",
                        "content": "نقش‌های ادمین و اپراتور دسترسی به بخش‌های حساس را کنترل می‌کنند و امکان فعال‌سازی 2FA وجود دارد.",
                    },
                    {
                        "title": "رمزنگاری توکن‌ها",
                        "content": "اعتبارنامه‌های OAuth و توکن‌های طولانی‌مدت به‌صورت رمزنگاری‌شده در پایگاه‌داده نگهداری می‌شوند.",
                    },
                ],
            },
        ]

    def _build_quick_links(self) -> List[Dict[str, str]]:
        return [
            {
                "title": "سند کامل الزامات",
                "description": "جزئیات معماری و قابلیت‌ها در فایل docs/project_spec.md قرار دارد.",
            },
            {
                "title": "راهنمای استقرار",
                "description": "برای اجرای محلی از اسکریپت‌های موجود در پوشه scripts و دستورات README.md استفاده کنید.",
            },
            {
                "title": "نکات توسعه افزونه‌ها",
                "description": "هر ماژول جدید باید Presenter و View مستقل با رعایت الگوی MVP داشته باشد.",
            },
        ]

    def _build_workflow(self) -> List[Dict[str, str]]:
        return [
            {
                "title": "ورود و احراز هویت",
                "details": "کاربر با نام کاربری/رمز عبور یا 2FA وارد شده و نقش او در پایگاه‌داده بررسی می‌شود.",
            },
            {
                "title": "تهیه منابع",
                "details": "سرویس‌های بیرونی (RSS، Pexels، OpenAI) فراخوانی شده و متن و رسانه خام گردآوری می‌شوند.",
            },
            {
                "title": "ساخت ویدیو",
                "details": "موتور تدوین، صحنه‌ها را براساس سناریو مونتاژ کرده و واترمارک «Benita Music» را درج می‌کند.",
            },
            {
                "title": "انتشار و گزارش‌دهی",
                "details": "پست‌ها طبق برنامه به پلتفرم‌ها ارسال و نتیجه در لاگ‌ها و اعلان‌ها ثبت می‌شود.",
            },
        ]

    def _build_api_endpoints(self) -> List[Dict[str, str]]:
        return [
            {
                "method": "GET",
                "path": "/api/jobs",
                "description": "دریافت وضعیت صف انتشار و آخرین اجراهای سناریوها.",
            },
            {
                "method": "POST",
                "path": "/api/jobs",
                "description": "ایجاد سناریو یا پست جدید برای برنامه‌ریز با تعیین حساب مقصد و زمان انتشار.",
            },
            {
                "method": "POST",
                "path": "/api/jobs/{job_id}/cancel",
                "description": "لغو اجرای در حال انتظار قبل از ارسال به پلتفرم هدف.",
            },
        ]

    def render(self, request: Request, user: models.AdminUser) -> object:
        context: Dict[str, Any] = {
            "request": request,
            "user": user,
            "active_page": "docs",
            "sections": self._build_sections(),
            "quick_links": self._build_quick_links(),
            "workflow_steps": self._build_workflow(),
            "api_endpoints": self._build_api_endpoints(),
        }
        return self.templates.TemplateResponse("documentation.html", context)
