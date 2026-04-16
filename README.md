# 农业资讯日报

自动抓取每日中国农业资讯，聚焦机械化、家庭农场、农业政策等主题，生成 Jekyll 博客文章并部署到 GitHub Pages，同时发送邮件摘要。

基于 [Minimal Mistakes](https://github.com/mmistakes/minimal-mistakes) 主题，纯 Markdown 渲染。

## 功能特性

- **自动抓取**：GitHub Actions 定时任务，每天北京时间 09:00 自动运行
- **多来源聚合**：农业农村部、中国农网、第一财经（农业标签）、虎嗅（农业关键词过滤）
- **并发爬取**：基于 `asyncio` + `aiohttp`，多来源并发抓取
- **双路输出**：
  - 每日 Markdown 文章（段落式汇总，存入 `_posts/`，发布为网站 post）
  - 邮件摘要（每条资讯一句话概括 + 来源链接，标题格式：`YYYY-MM-DD 农业资讯`）
- **增量更新**：跳过已抓取的日期，避免重复

## 项目结构

```
agri_news/
├── _config.yml               # Jekyll 站点配置
├── _posts/                   # 生成的农业资讯 Markdown 文章
├── _layouts/
│   └── single-with-ga.html   # 文章布局（含 Google Analytics）
├── _includes/
│   └── analytics.html        # GA 跟踪代码
├── _data/
│   └── subsites.yml          # 子站点元数据
├── scripts/
│   └── agri_news_crawler.py  # 农业资讯爬虫主脚本（含邮件发送）
├── .github/workflows/
│   └── agri_deploy.yml       # CI/CD 定时任务
├── Gemfile
└── index.html                # 首页
```

## 数据来源

| 来源 | 抓取入口 | 备注 |
|------|----------|------|
| [农业农村部](https://www.moa.gov.cn/xw/zwdt/) | 部动态 | |
| [农业农村部·部门动态](https://www.moa.gov.cn/xw/bmdt/) | 部门动态 | |
| [中国农网](https://www.farmer.com.cn/xwpd/nync/) | 农业新闻 | 按文章 URL 模式匹配 |
| [第一财经](https://www.yicai.com/news/?tag=农业) | 农业标签 | |
| [虎嗅](https://www.huxiu.com/) | 首页 | 农业关键词过滤 |

## 配置邮件通知

在 GitHub 仓库 Settings → Secrets and variables → Actions 中添加以下 Secrets：

| Secret 名称 | 说明 |
|------------|------|
| `SMTP_HOST` | SMTP 服务器地址（如 `smtp.gmail.com`） |
| `SMTP_PORT` | SMTP 端口（如 `587`） |
| `SMTP_USER` | 发件邮箱地址 |
| `SMTP_PASS` | 邮箱密码或应用专用密码 |
| `EMAIL_TO` | 收件邮箱地址 |

## 本地开发

### 前置依赖

- Ruby >= 3.0
- Python >= 3.10
- Bundler

### 运行爬虫

```bash
# 安装 Python 依赖
pip install aiohttp beautifulsoup4 lxml

# 抓取今日农业资讯
python scripts/agri_news_crawler.py
```

### 本地预览 Jekyll 站点

```bash
bundle install
bundle exec jekyll serve
```

访问 `http://localhost:4000/agri_news/` 查看效果。

## 许可

MIT
