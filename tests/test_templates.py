import pathlib
import sys
from datetime import datetime
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, select_autoescape

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))


def test_scheduler_template_renders_job_row():
    account = SimpleNamespace(id=1, display_name="اکانت تست", platform="instagram")
    scheduled_time = datetime(2024, 5, 20, 14, 45)
    post = SimpleNamespace(
        id=7,
        title="تیزر تابستانی",
        content="پیش‌نمایش محتوای جذاب تابستانی",
        video_url="https://cdn.example.com/video.mp4",
        scheduled_time=scheduled_time,
        status="pending",
        account=account,
    )

    env = Environment(
        loader=FileSystemLoader("app/templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.globals["url_for"] = lambda name, **kwargs: f"/static/{kwargs.get('path', '')}"

    template = env.get_template("scheduler.html")
    html = template.render(
        user=SimpleNamespace(username="admin"),
        accounts=[account],
        posts=[post],
        active_page="scheduler",
    )

    expected_snippet = (
        "<td>تیزر تابستانی</td>"\
        "\n                                <td>اکانت تست</td>"\
        f"\n                                <td>{scheduled_time.strftime('%Y-%m-%d %H:%M')}</td>"\
        "\n                                <td><span class=\"badge badge-secondary text-uppercase\">pending</span></td>"
    )

    assert expected_snippet in html
    assert "data-video=\"https://cdn.example.com/video.mp4\"" in html
    assert "پیش‌نمایش محتوای جذاب تابستانی" in html
