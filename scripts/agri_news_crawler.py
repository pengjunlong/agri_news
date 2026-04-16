#!/usr/bin/env python3
"""
中国农业新闻爬虫 — 聚焦机械化、家庭农场、农业政策等主题
来源：
  - 农业农村部 (moa.gov.cn)        — 部动态 + 农机化频道
  - 中国农网 (farmer.com.cn)       — 农业新闻
  - 第一财经 (yicai.com)           — 农业标签
  - 36氪 (36kr.com)               — 农业关键词
  - 虎嗅 (huxiu.com)              — 农业关键词过滤

输出：
  1. 每日 Markdown 文章（存入 _posts/）— 按来源分组，段落式汇总
  2. 通过 SMTP 发送邮件摘要（每条新闻一句话 + 来源链接）
"""

import aiohttp
import asyncio
import logging
import os
import random
import re
import smtplib
import ssl
import sys
from bs4 import BeautifulSoup
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
}

MAX_CONCURRENT = 3
MAX_RETRIES = 3
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
BASE_DELAY = (0.5, 2.0)
MAX_ITEMS_PER_SOURCE = 8

# 农业主题关键词（用于虎嗅等综合媒体的过滤）
AGRI_KEYWORDS = [
    "农业", "农村", "农民", "三农", "粮食", "种植", "养殖", "畜牧",
    "农机", "机械化", "家庭农场", "耕地", "乡村", "丰收", "农产品",
    "种子", "化肥", "农药", "灌溉", "智慧农业", "数字农业", "农业科技",
    "合作社", "土地", "水稻", "小麦", "玉米", "大豆", "棉花",
]

# post 文件名前缀与邮件主题中的主题词
TOPIC_NAME = "农业"
POST_SUFFIX = "agri-news"
EMAIL_SUBJECT_SUFFIX = "农业资讯"


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------
@dataclass
class NewsArticle:
    title: str
    url: str
    summary: str
    source: str
    source_url: str


# ---------------------------------------------------------------------------
# 来源配置
# ---------------------------------------------------------------------------
SOURCES = [
    {
        "name": "农业农村部",
        "url": "https://www.moa.gov.cn/xw/zwdt/",
        "home": "https://www.moa.gov.cn",
        "type": "moa",
    },
    {
        "name": "农业农村部·部门动态",
        "url": "https://www.moa.gov.cn/xw/bmdt/",
        "home": "https://www.moa.gov.cn",
        "type": "moa",
    },
    {
        "name": "中国农网",
        "url": "https://www.farmer.com.cn/xwpd/nync/",
        "home": "https://www.farmer.com.cn",
        "type": "farmer",
    },
    {
        "name": "第一财经",
        "url": "https://www.yicai.com/news/?tag=%E5%86%9C%E4%B8%9A",  # 农业
        "home": "https://www.yicai.com",
        "type": "yicai",
    },
    {
        "name": "虎嗅",
        "url": "https://www.huxiu.com/",
        "home": "https://www.huxiu.com",
        "type": "huxiu",
    },
]


# ---------------------------------------------------------------------------
# 各来源解析器
# ---------------------------------------------------------------------------

def parse_moa(html: str, base_url: str) -> List[dict]:
    """解析农业农村部新闻列表 — 按 .htm URL 模式匹配"""
    soup = BeautifulSoup(html, "lxml")
    articles = []
    seen_urls = set()

    for a in soup.find_all("a", href=re.compile(r"moa\.gov\.cn/.+\.htm")):
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not href or not title or len(title) < 6:
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        if not href.startswith("http"):
            href = base_url + href

        articles.append({"title": title, "url": href, "summary": ""})
        if len(articles) >= MAX_ITEMS_PER_SOURCE:
            break

    return articles


def parse_farmer(html: str, base_url: str) -> List[dict]:
    """解析中国农网 — 按 farmer.com.cn/YYYY 文章 URL 模式"""
    soup = BeautifulSoup(html, "lxml")
    articles = []
    seen_urls = set()

    # 文章链接格式: /YYYY/MM/DD/NNNNN.html
    pat = re.compile(r"farmer\.com\.cn/\d{4}/\d{2}/\d{2}/\d+")
    for a in soup.find_all("a", href=pat):
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not href or not title or len(title) < 6:
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        if not href.startswith("http"):
            href = base_url + href

        articles.append({"title": title, "url": href, "summary": ""})
        if len(articles) >= MAX_ITEMS_PER_SOURCE:
            break

    # 如果专用 URL 模式无结果，回退到通用链接抓取
    if not articles:
        for a in soup.find_all("a", href=re.compile(r"farmer\.com\.cn")):
            href = a.get("href", "")
            title = a.get_text(strip=True)
            if not href or not title or len(title) < 8:
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)
            articles.append({"title": title, "url": href, "summary": ""})
            if len(articles) >= MAX_ITEMS_PER_SOURCE:
                break

    return articles


def _clean_yicai_title(raw_text: str) -> str:
    """第一财经链接文本包含 标题+摘要+时间，提取纯标题"""
    text = re.sub(
        r'\d+分钟前.*$|\d+小时前.*$|\d+天前.*$|\d{4}-\d{2}-\d{2}.*$',
        '', raw_text
    ).strip()
    title_end = re.search(r'[。！？]', text)
    if title_end and title_end.start() <= 60:
        return text[: title_end.start() + 1].strip()
    return text[:50].strip()


def parse_yicai(html: str, base_url: str) -> List[dict]:
    """解析第一财经标签页"""
    soup = BeautifulSoup(html, "lxml")
    articles = []
    seen_urls = set()

    for a in soup.select("a[href*='/news/']"):
        href = a.get("href", "")
        raw_text = a.get_text(strip=True)
        if not href or not raw_text or len(raw_text) < 8:
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        if not href.startswith("http"):
            href = base_url + href

        title = _clean_yicai_title(raw_text)
        if len(title) < 5:
            continue

        full = re.sub(
            r'\d+分钟前.*$|\d+小时前.*$|\d+天前.*$|\d{4}-\d{2}-\d{2}.*$',
            '', raw_text
        ).strip()
        summary = full[len(title):].strip()[:80] if len(full) > len(title) else ""

        articles.append({"title": title, "url": href, "summary": summary})
        if len(articles) >= MAX_ITEMS_PER_SOURCE:
            break

    return articles


def parse_huxiu(html: str, base_url: str) -> List[dict]:
    """解析虎嗅首页，按农业关键词过滤"""
    soup = BeautifulSoup(html, "lxml")
    articles = []
    seen_urls = set()

    for a in soup.find_all("a", href=re.compile(r"/article/\d+\.html")):
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not href or not title or len(title) < 8 or len(title) > 150:
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        if not href.startswith("http"):
            href = base_url + href

        is_agri = any(kw in title for kw in AGRI_KEYWORDS)
        articles.append({"title": title, "url": href, "summary": "", "is_agri": is_agri})

    agri = [a for a in articles if a.get("is_agri")]
    other = [a for a in articles if not a.get("is_agri")]
    result = (agri + other)[:MAX_ITEMS_PER_SOURCE]
    return [{"title": a["title"], "url": a["url"], "summary": ""} for a in result]


PARSERS = {
    "moa": parse_moa,
    "farmer": parse_farmer,
    "yicai": parse_yicai,
    "huxiu": parse_huxiu,
}


# ---------------------------------------------------------------------------
# 摘要提取（从文章详情页）
# ---------------------------------------------------------------------------
def extract_article_summary(html: str, existing_summary: str = "") -> str:
    """从文章详情页提取一句话摘要"""
    if existing_summary and len(existing_summary) >= 20:
        s = re.sub(r"\s+", " ", existing_summary).strip()
        return s[:100] + ("…" if len(s) > 100 else "")

    if not html:
        return ""

    soup = BeautifulSoup(html, "lxml")

    # 优先 meta description / og:description
    for attr in ({"name": "description"}, {"property": "og:description"}):
        meta = soup.find("meta", attrs=attr)
        if meta and meta.get("content"):
            s = meta["content"].strip()
            if len(s) >= 15:
                return s[:120] + ("…" if len(s) > 120 else "")

    # 正文首段
    for selector in (
        "div.article-content p",
        "div.TRS_Editor p",
        "div.post-content p",
        "div.entry-content p",
        "article p",
        ".content p",
        "p",
    ):
        for p in soup.select(selector):
            text = p.get_text(strip=True)
            if len(text) >= 20:
                return text[:120] + ("…" if len(text) > 120 else "")

    return ""


# ---------------------------------------------------------------------------
# Markdown 生成
# ---------------------------------------------------------------------------
def generate_front_matter(date_str: str) -> str:
    return f"""---
layout: single-with-ga
classes: wide
title: "{date_str} 农业资讯日报"
date: {date_str} 08:00:00 +0800
categories: agri-news
tags: [农业, 机械化, 家庭农场, 农村政策]
---

"""


def generate_markdown_body(articles: List[NewsArticle], date_str: str) -> str:
    """生成按来源分组的段落式汇总 Markdown"""
    parts: List[str] = []

    parts.append(f"## {date_str} 农业动态")
    parts.append("")
    parts.append(
        f"> 本文汇总来自 **农业农村部、中国农网、第一财经、虎嗅** 的农业资讯，"
        f"聚焦机械化、家庭农场、政策动态，共 {len(articles)} 条。"
    )
    parts.append("")
    parts.append("---")
    parts.append("")

    source_order = [s["name"] for s in SOURCES]
    source_groups: dict = {}
    for art in articles:
        source_groups.setdefault(art.source, []).append(art)

    for src_name in source_order:
        items = source_groups.get(src_name, [])
        if not items:
            continue
        parts.append(f"### 🌾 {src_name}")
        parts.append("")
        for art in items:
            parts.append(f"**[{art.title}]({art.url})**")
            parts.append("")
            if art.summary:
                parts.append(f"{art.summary}")
                parts.append("")
        parts.append("---")
        parts.append("")

    parts.append(
        "*数据来源：[农业农村部](https://www.moa.gov.cn) · "
        "[中国农网](https://www.farmer.com.cn) · "
        "[第一财经](https://www.yicai.com) · "
        "[虎嗅](https://www.huxiu.com)*"
    )

    return "\n".join(parts)


def write_post(output_dir: Path, date_str: str, articles: List[NewsArticle]) -> Path:
    filename = output_dir / f"{date_str}-{POST_SUFFIX}.md"
    output_dir.mkdir(parents=True, exist_ok=True)
    body = generate_markdown_body(articles, date_str)
    full_content = generate_front_matter(date_str) + body
    filename.write_text(full_content, encoding="utf-8")
    logger.info("已生成: %s", filename)
    return filename


# ---------------------------------------------------------------------------
# 邮件发送
# ---------------------------------------------------------------------------
def build_email_content(articles: List[NewsArticle], date_str: str) -> tuple[str, str]:
    """构建邮件纯文本和 HTML 正文"""
    source_order = [s["name"] for s in SOURCES]
    source_groups: dict = {}
    for art in articles:
        source_groups.setdefault(art.source, []).append(art)

    # 纯文本
    text_lines = [f"{date_str} {EMAIL_SUBJECT_SUFFIX}", "=" * 40, ""]
    for src in source_order:
        items = source_groups.get(src, [])
        if not items:
            continue
        text_lines.append(f"【{src}】")
        for art in items:
            summary = art.summary if art.summary else art.title
            one_line = summary[:80] + ("…" if len(summary) > 80 else "")
            text_lines.append(f"• {one_line}")
            text_lines.append(f"  来源：{art.url}")
            text_lines.append("")
        text_lines.append("")
    text_body = "\n".join(text_lines)

    # HTML
    html_lines = [
        "<html><body style='font-family:Arial,sans-serif;max-width:700px;margin:0 auto'>",
        f"<h2 style='color:#2d6a2d'>{date_str} {EMAIL_SUBJECT_SUFFIX}</h2>",
        "<hr style='border:1px solid #eee'>",
    ]
    for src in source_order:
        items = source_groups.get(src, [])
        if not items:
            continue
        html_lines.append(f"<h3 style='color:#3a7d3a;margin-top:20px'>🌾 {src}</h3>")
        html_lines.append("<ul style='line-height:1.8'>")
        for art in items:
            summary = art.summary if art.summary else art.title
            one_line = summary[:100] + ("…" if len(summary) > 100 else "")
            html_lines.append(
                f"<li><span style='color:#222'>{one_line}</span>"
                f"<br><small style='color:#999'>来源：<a href='{art.url}' style='color:#2d6a2d'>{art.url[:80]}</a></small></li>"
            )
        html_lines.append("</ul>")
    html_lines.extend([
        "<hr style='border:1px solid #eee;margin-top:30px'>",
        "<p style='color:#999;font-size:12px'>数据来源：农业农村部 · 中国农网 · 第一财经 · 虎嗅</p>",
        "</body></html>",
    ])
    html_body = "\n".join(html_lines)
    return text_body, html_body


def send_email(articles: List[NewsArticle], date_str: str) -> bool:
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT") or "587")
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    email_to = os.environ.get("EMAIL_TO", "")

    if not all([smtp_user, smtp_pass, email_to]):
        logger.warning("邮件配置不完整，跳过发送（需设置 SMTP_USER/SMTP_PASS/EMAIL_TO）")
        return False

    subject = f"{date_str} {EMAIL_SUBJECT_SUFFIX}"
    text_body, html_body = build_email_content(articles, date_str)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = email_to
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [email_to], msg.as_string())
        logger.info("邮件已发送至 %s，主题：%s", email_to, subject)
        return True
    except Exception as e:
        logger.error("邮件发送失败: %s", e)
        return False


# ---------------------------------------------------------------------------
# 异步爬虫
# ---------------------------------------------------------------------------
class AgriNewsCrawler:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        self.ssl_ctx = ssl.create_default_context()
        self.ssl_ctx.check_hostname = False
        self.ssl_ctx.verify_mode = ssl.CERT_NONE

    async def _fetch(
        self,
        session: aiohttp.ClientSession,
        url: str,
        encoding: str = "utf-8",
        ssl_verify: bool = True,
    ) -> str:
        """带重试和信号量的 HTTP GET"""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with self.semaphore:
                    await asyncio.sleep(random.uniform(*BASE_DELAY))
                    ssl_param = True if ssl_verify else self.ssl_ctx
                    async with session.get(
                        url, timeout=REQUEST_TIMEOUT, ssl=ssl_param
                    ) as resp:
                        if resp.status != 200:
                            raise ValueError(f"HTTP {resp.status} for {url}")
                        raw = await resp.read()
                        return raw.decode(encoding, errors="replace")
            except Exception as exc:
                if attempt == MAX_RETRIES:
                    logger.error("抓取失败 %s: %s", url, exc)
                    return ""
                wait = 2 ** attempt + random.random()
                logger.warning("第 %d 次重试 %s（原因: %s）", attempt, url, exc)
                await asyncio.sleep(wait)
        return ""

    async def crawl_source(
        self, session: aiohttp.ClientSession, source: dict
    ) -> List[NewsArticle]:
        name = source["name"]
        url = source["url"]
        home = source["home"]
        src_type = source["type"]
        encoding = source.get("encoding", "utf-8")
        ssl_verify = url.startswith("https://")

        logger.info("抓取 %s ...", name)
        html = await self._fetch(session, url, encoding=encoding, ssl_verify=ssl_verify)
        if not html:
            logger.warning("%s 列表页抓取失败", name)
            return []

        parser = PARSERS.get(src_type)
        raw_articles = parser(html, home) if parser else []

        if not raw_articles:
            logger.warning("%s 未解析到文章", name)
            return []

        logger.info("%s 解析到 %d 条文章", name, len(raw_articles))

        # 逐条获取详情页摘要
        articles: List[NewsArticle] = []
        fetch_tasks = []
        for raw in raw_articles[:MAX_ITEMS_PER_SOURCE]:
            if raw.get("summary") and len(raw["summary"]) >= 20:
                fetch_tasks.append(None)
            else:
                fetch_tasks.append(
                    self._fetch(session, raw["url"], encoding=encoding, ssl_verify=ssl_verify)
                )

        detail_htmls = []
        for task in fetch_tasks:
            if task is None:
                detail_htmls.append("")
            else:
                detail_htmls.append(await task)

        for i, raw in enumerate(raw_articles[:MAX_ITEMS_PER_SOURCE]):
            summary = extract_article_summary(detail_htmls[i], raw.get("summary", ""))
            articles.append(
                NewsArticle(
                    title=raw["title"],
                    url=raw["url"],
                    summary=summary,
                    source=name,
                    source_url=home,
                )
            )

        return articles

    async def run(self) -> List[NewsArticle]:
        """并发抓取所有来源"""
        connector = aiohttp.TCPConnector(limit=MAX_CONCURRENT, force_close=False)
        async with aiohttp.ClientSession(
            headers=HEADERS, connector=connector, trust_env=True
        ) as session:
            tasks = [self.crawl_source(session, src) for src in SOURCES]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_articles: List[NewsArticle] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("某来源抓取异常: %s", result)
            elif isinstance(result, list):
                all_articles.extend(result)

        logger.info("共抓取到 %d 条农业资讯", len(all_articles))
        return all_articles


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main():
    now = datetime.now(TZ_SHANGHAI)
    date_str = now.strftime("%Y-%m-%d")
    output_dir = Path(__file__).resolve().parent.parent / "_posts"
    target_file = output_dir / f"{date_str}-{POST_SUFFIX}.md"

    if target_file.exists():
        logger.info("今日文章已存在: %s，跳过", target_file.name)
        return 0

    logger.info("开始抓取 %s 的农业资讯", date_str)
    crawler = AgriNewsCrawler()
    articles = asyncio.run(crawler.run())

    if not articles:
        logger.error("未抓取到任何资讯，退出")
        return 1

    write_post(output_dir, date_str, articles)
    send_email(articles, date_str)
    logger.info("完成，共处理 %d 条资讯", len(articles))
    return 0


if __name__ == "__main__":
    sys.exit(main())

