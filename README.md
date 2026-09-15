# HeyBlog WebScraper

面向博客 / 内容站点的网页抓取工具库。给定一个 URL，采集其基础信息并统一产出结构化的
`UrlInfo`：首页元数据、可见正文、RSS/Atom/JSON Feed 的发现与解析、关于页、常见路径探测，
以及建站技术栈信号。

> 本包原名 `HeyBlog_Model_Util`（import `heyblog_model_util`），因其真实定位是「网页抓取工具」
> 而重命名为 `heyblog_webscraper`。公共 API 的符号名保持不变，仅导入路径与内部结构调整。

## 安装

作为 sibling path 依赖被 `HeyBlog_Model`、`HeyBlog_Model_Agent` 及主仓库 `HeyBlog_Model_API`
以可编辑方式引用：

```toml
[tool.uv.sources]
heyblog-webscraper = { path = "../HeyBlog_WebScraper", editable = true }
```

单独开发时：`uv sync`（含 `--extra dev` 获取 pytest）。

包源码直接位于 `src/`；构建配置会将该目录映射为 Python 包
`heyblog_webscraper`，调用方的导入方式不变。

## 快速上手

```python
from heyblog_webscraper import collect_url_info, UrlInfoOptions

info = collect_url_info("https://example.com/", options=UrlInfoOptions(max_feed_items=5))
print(info.status, info.final_url)
print(info.feed.feed_url if info.feed else "no feed")
for article in (info.feed.articles if info.feed else []):
    print(article.title, article.url)
```

固定预算的轻量采集使用 `collect_basic_url_info(url)`。它会规范化输入并固定采用 10 秒总预算、
4 秒单请求超时、最多 3 个 Feed 候选、1 个 ABOUT 页面和 1 个图标，不抓取 Feed 文章或文章页。
返回的 `BasicUrlInfoResult` 包含完整内部 `info` 快照、独立 `resources`、验证后的 `icon` 和
聚合 `timing`；HTTP
服务应将其投影到自己的版本化响应模型，而不是直接暴露内部快照。

主入口 `collect_url_info(url, *, options=None, fetcher=None) -> UrlInfo` 会：校验并归一化 URL
（含 SSRF 防护）→ 抓取首页 → 解析页面元数据/正文/技术栈信号 → 发现并解析 feed →
逐篇补全文章正文 → 探测常见路径与关联页面 → 汇总为 `UrlInfo`。

## 内部结构

按职责分层，每个子包的 `__init__.py` 统一重新导出公共符号：

| 层 | 模块 | 职责 |
| --- | --- | --- |
| 数据模型 | `models.py` | 对外结果模型（pydantic v2，`extra="forbid"`） |
| 选项 | `options.py` | 抓取选项 `UrlInfoOptions` 与预设 |
| 网络层 | `net/` (`urls`, `client`, `encoding`) | URL 校验/归一化、HTTP 抓取、响应解码；含 SSRF 双重防护与安全重定向 |
| 解析层 | `parsing/` (`html`, `feeds`) | HTML 页面解析、feed 发现与解析（defusedxml） |
| 采集编排 | `collector/` (`pipeline`, `feeds`, `pages`, `signals`, `support`) | 串联各阶段，主入口 `collect_url_info` |

调用方只需 `from heyblog_webscraper import ...`，无需关心内部拆分。

## 安全（SSRF 防护）

- `validate_public_http_url`：字面层拦截非 http(s)、用户信息/片段、本地主机名与私有/本地
  IP（含十进制/十六进制/八进制/IPv6 变体）；
- `validate_resolved_public_host`（`heyblog_webscraper.net`）：在字面校验之上追加 DNS 解析校验；
- 抓取过程对每一跳重定向都重新过一遍主机校验。

## 测试

```bash
uv run --extra dev pytest -q
```

`tests/` 覆盖 URL 采集主流程、feed 发现/解析与 SSRF 防护（`test_ssrf_guards.py`）。
