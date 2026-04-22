"""
UN Careers 实习岗位列表抓取（Playwright 异步）+ 按 date_logic 过滤并随机抽取。
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
import traceback
from datetime import date
from typing import Optional

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from date_logic import should_keep_deadline

LIST_URL = (
    "https://careers.un.org/jobopening?language=en&data="
    "%257B%2522aoe%2522:%255B%255D,%2522aoi%2522:%255B%255D,%2522el%2522:%255B%255D,"
    "%2522ct%2522:%255B%255D,%2522ds%2522:%255B%255D,%2522jn%2522:%255B%255D,"
    "%2522jf%2522:%255B%255D,%2522jc%2522:%255B%2522INT%2522%255D,%2522jle%2522:%255B%255D,"
    "%2522dept%2522:%255B%255D,%2522span%2522:%255B%255D%257D"
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 候选池确定后，随机抽取进入详情抓取的条数（可被环境变量 CRAWLER_SAMPLE_SIZE 覆盖）
CRAWLER_SAMPLE_SIZE = 13

# CloudFront 可能对无头浏览器返回 403，使用常见桌面 UA 与语言头更接近真实浏览器。
EXTRA_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _playwright_headless_from_env() -> bool:
    """默认 True；设置 PLAYWRIGHT_HEADLESS=false 可关闭无头（本地调试）。"""
    v = (os.getenv("PLAYWRIGHT_HEADLESS") or "true").strip().lower()
    return v in ("1", "true", "yes", "on")

# 仅匹配「Deadline」标签后的日期，避免误抓 Date Posted。
PAIR_SCRIPT = r"""
() => {
  function deadlineFromText(text) {
    if (!text) return null;
    const m = text.match(/Deadline\s*:?\s*([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})/i);
    return m ? m[1] : null;
  }

  const out = [];
  const links = Array.from(document.querySelectorAll("a")).filter((a) => {
    const t = (a.innerText || "").trim();
    return t === "View Job Description" && (a.href || "").includes("jobSearchDescription");
  });

  for (const a of links) {
    let el = a;
    let deadline = null;
    for (let i = 0; i < 20 && el; i++) {
      const text = el.innerText || "";
      deadline = deadlineFromText(text);
      if (deadline) break;
      el = el.parentElement;
    }
    if (deadline) {
      out.push({ deadline: deadline, url: a.href });
    }
  }
  return out;
}
"""


async def _collect_pairs(page: Page) -> list[dict[str, str]]:
    raw: list[dict[str, str]] = await page.evaluate(PAIR_SCRIPT)
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for row in raw:
        u = row.get("url", "")
        if not u or u in seen:
            continue
        seen.add(u)
        out.append({"deadline": row["deadline"], "url": u})
    return out


def build_candidate_pool(
    rows: list[dict[str, str]], today: Optional[date] = None
) -> list[dict[str, str]]:
    """
    列表已按 Deadline 升序。自上而下找到第一条 should_keep_deadline 为 True 的记录，
    保留该条及之后的所有记录作为候选池。
    """
    for i, r in enumerate(rows):
        try:
            if should_keep_deadline(r["deadline"], today):
                return rows[i:]
        except ValueError:
            continue
    return []


async def _set_records_per_page_50(page: Page) -> None:
    """在「Search Criteria」展开后，将右上角 Records per Page 设为 50。"""
    rpp_toggle = page.locator("button.dropdown-toggle.btn.tiny-select").nth(1)
    await rpp_toggle.wait_for(state="visible", timeout=60_000)
    await rpp_toggle.click(timeout=60_000)
    await page.wait_for_timeout(500)
    await page.locator('button.dropdown-item[aria-label="Limit to 50 Jobs"]').click(
        timeout=60_000
    )
    await page.wait_for_load_state("networkidle", timeout=120_000)
    await page.wait_for_timeout(2500)


async def _set_sort_deadline_ascending(page: Page) -> None:
    sort_toggle = page.locator("button.dropdown-toggle.btn.tiny-select").nth(0)
    await sort_toggle.wait_for(state="visible", timeout=60_000)
    await sort_toggle.click(timeout=60_000)
    await page.wait_for_timeout(500)
    await page.get_by_role("button", name="Deadline Ascending").click(timeout=60_000)
    await page.wait_for_load_state("networkidle", timeout=120_000)
    await page.wait_for_timeout(2000)


async def _click_next_page(page: Page) -> bool:
    """点击分页「Next」；若不存在或已禁用则返回 False。"""
    nxt = page.locator('a[aria-label="Next"]')
    if await nxt.count() == 0:
        return False
    link = nxt.first
    li = link.locator("xpath=ancestor::li[1]")
    cls = (await li.get_attribute("class")) or ""
    if "disabled" in cls:
        return False
    await link.click(timeout=60_000)
    await page.wait_for_load_state("networkidle", timeout=120_000)
    await page.wait_for_timeout(2000)
    await page.get_by_text("View Job Description", exact=True).first.wait_for(
        state="visible", timeout=60_000
    )
    return True


async def fetch_internship_page(
    simulated_today: Optional[date] = None,
    max_pages: int = 3,
    min_pool_size: int = 20,
) -> list[dict[str, str]]:
    """
    抓取列表（每页最多 50 条），必要时翻页，直到候选池不少于 min_pool_size 或达到 max_pages。

    :param simulated_today: 传入虚拟「今天」用于测试过滤；None 表示使用系统日期。
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=_playwright_headless_from_env(),
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            context = await browser.new_context(
                user_agent=USER_AGENT,
                locale="en-US",
                extra_http_headers=EXTRA_HEADERS,
            )
            page = await context.new_page()
            try:
                await page.goto(LIST_URL, wait_until="domcontentloaded", timeout=120_000)
                await page.wait_for_load_state("networkidle", timeout=120_000)
                await page.wait_for_timeout(1500)

                await page.get_by_text("Search Criteria", exact=False).first.click(
                    timeout=60_000
                )
                await page.wait_for_timeout(800)

                await _set_records_per_page_50(page)
                await _set_sort_deadline_ascending(page)

                await page.get_by_text(
                    "View Job Description", exact=True
                ).first.wait_for(state="visible", timeout=60_000)

                all_rows: list[dict[str, str]] = []
                seen_urls: set[str] = set()

                for page_index in range(max_pages):
                    if page_index > 0:
                        moved = await _click_next_page(page)
                        if not moved:
                            break

                    chunk = await _collect_pairs(page)
                    for row in chunk:
                        u = row["url"]
                        if u in seen_urls:
                            continue
                        seen_urls.add(u)
                        all_rows.append(row)

                    pool = build_candidate_pool(all_rows, simulated_today)
                    if len(pool) >= min_pool_size:
                        break

                return all_rows
            except (PlaywrightTimeoutError, PlaywrightError) as e:
                print("Playwright 错误:", e, file=sys.stderr)
                traceback.print_exc()
                return []
            except Exception as e:
                print("抓取过程未预期错误:", e, file=sys.stderr)
                traceback.print_exc()
                return []
            finally:
                await context.close()
        finally:
            await browser.close()


# 设为 None 使用系统真实日期；设为 date(2026, 4, 12) 可模拟 12 日过滤规则。
SIMULATED_TODAY: Optional[date] = None


async def fetch_candidate_urls(
    simulated_today: Optional[date] = None,
    *,
    max_pages: int | None = None,
    min_pool_size: int | None = None,
    sample_size: int | None = None,
) -> list[str]:
    """
    流水线入口：抓取列表页，按日期规则得到候选池并随机抽样，返回详情页 URL 列表。
    """
    max_pages_i = max_pages if max_pages is not None else int(
        os.getenv("CRAWLER_MAX_PAGES", "3")
    )
    min_pool_i = min_pool_size if min_pool_size is not None else int(
        os.getenv("CRAWLER_MIN_POOL_SIZE", "20")
    )
    sample_i = sample_size if sample_size is not None else int(
        os.getenv("CRAWLER_SAMPLE_SIZE", str(CRAWLER_SAMPLE_SIZE))
    )

    rows = await fetch_internship_page(
        simulated_today=simulated_today,
        max_pages=max_pages_i,
        min_pool_size=min_pool_i,
    )
    if not rows:
        return []

    pool = build_candidate_pool(rows, simulated_today)
    if not pool:
        return []

    k = min(sample_i, len(pool))
    try:
        picked = random.sample(pool, k)
    except ValueError:
        picked = pool
    return [str(item["url"]).strip() for item in picked if item.get("url")]


def main() -> None:
    # Windows 控制台默认编码可能非 UTF-8，避免中文打印报错
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    try:
        urls = asyncio.run(fetch_candidate_urls(simulated_today=SIMULATED_TODAY))
    except Exception as e:
        print("asyncio.run 失败:", e, file=sys.stderr)
        traceback.print_exc()
        return

    if not urls:
        print("未获得任何候选 URL（列表为空、过滤后无池或网络问题）。")
        return

    print(f"随机输出 {len(urls)} 条 URL：\n")
    for i, u in enumerate(urls, 1):
        print(f"{i}. URL: {u}\n")


if __name__ == "__main__":
    main()
