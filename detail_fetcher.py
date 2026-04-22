"""
UN Careers 详情页深度提取（Playwright 异步）。
展开折叠区块后抓取职位标题、灰框信息、工作地点、期限及 AI 用合并描述块。
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import sys
import traceback
from typing import Any, Optional

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

EXTRA_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _playwright_headless_from_env() -> bool:
    """默认 True；本地调试可设 PLAYWRIGHT_HEADLESS=false。"""
    v = (os.getenv("PLAYWRIGHT_HEADLESS") or "true").strip().lower()
    return v in ("1", "true", "yes", "on")


def _playwright_slow_mo_ms() -> int:
    raw = (os.getenv("PLAYWRIGHT_SLOW_MO_MS") or "0").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0

RESULTS_JSON_PATH = os.getenv("DETAIL_RESULTS_JSON_PATH", "test_results.json")

# 需确保展开的关键栏目（标题需与页面完全一致）
PRIORITY_SECTION_TITLES: tuple[str, ...] = (
    "Work Location",
    "Expected duration",
    "Responsibilities",
    "Duties and Responsibilities",
    "Qualifications/special skills",
)

EXTRACT_SCRIPT = r"""
() => {
  function accordionBody(exactTitle) {
    const headers = Array.from(document.querySelectorAll("a.inspira-accordion-header"));
    const h = headers.find((a) => (a.innerText || "").trim() === exactTitle);
    if (!h) return null;
    let n = h.nextElementSibling;
    while (n && !(n.innerText || "").trim()) n = n.nextElementSibling;
    if (!n) return null;
    return (n.innerText || "");
  }

  function grayBoxText() {
    const cards = Array.from(document.querySelectorAll("div.card"));
    const card = cards.find((c) => (c.innerText || "").includes("Duty Station"));
    return card ? (card.innerText || "") : null;
  }

  const h1 = document.querySelector("h1");
  const jobTitle = h1 ? (h1.innerText || "").trim() : null;

  const grayRaw = grayBoxText();
  const pickLine = (label) => {
    if (!grayRaw) return null;
    const re = new RegExp(label + "\\s*:\\s*([^\\n]+)", "i");
    const m = grayRaw.match(re);
    return m ? m[1].trim() : null;
  };

  const gray_box_details = grayRaw
    ? {
        duty_station: pickLine("Duty Station"),
        department_office: pickLine("Department/Office"),
        deadline: pickLine("Deadline"),
      }
    : null;

  const work_location = accordionBody("Work Location");
  const expected_duration = accordionBody("Expected duration");

  let resp = accordionBody("Responsibilities");
  if (resp == null) resp = accordionBody("Duties and Responsibilities");

  const qual = accordionBody("Qualifications/special skills");

  return {
    job_title: jobTitle,
    gray_box_details,
    work_location,
    expected_duration,
    responsibilities_raw: resp,
    qualifications_raw: qual,
  };
}
"""


def _merge_full_description(
    responsibilities: Optional[str], qualifications: Optional[str]
) -> Optional[str]:
    parts: list[str] = []
    if responsibilities is not None and str(responsibilities).strip() != "":
        parts.append(str(responsibilities))
    if qualifications is not None and str(qualifications).strip() != "":
        parts.append(str(qualifications))
    if not parts:
        return None
    return "\n\n".join(parts)


async def _delay_between_requests() -> None:
    await asyncio.sleep(random.uniform(1.0, 2.0))


async def _expand_job_page(page: Page) -> None:
    """展开详情页折叠内容：优先 Expand All（勿再点同一批标题，否则会再次收起）。"""
    print("[展开] 开始处理折叠区块…", flush=True)
    expand_btn = page.get_by_role("button", name=re.compile(r"^\s*Expand All\s*$", re.I))
    used_expand_all = False
    if await expand_btn.count() > 0:
        print('[展开] 正在点击「Expand All」…', flush=True)
        await expand_btn.first.click(timeout=60_000)
        await page.wait_for_timeout(1200)
        used_expand_all = True
        print('[展开] 「Expand All」已点击，等待内容渲染…', flush=True)
    else:
        print("[展开] 未找到「Expand All」，将尝试逐栏点击。", flush=True)
        await page.wait_for_timeout(400)

    # 仅在没有「Expand All」时逐一点击关键栏目，避免与 Expand All 重复点击导致折叠
    if not used_expand_all:
        for title in PRIORITY_SECTION_TITLES:
            print(f"[展开] 正在尝试展开「{title}」…", flush=True)
            link = page.locator("a.inspira-accordion-header").filter(
                has_text=re.compile(rf"^\s*{re.escape(title)}\s*$")
            )
            try:
                if await link.count() == 0:
                    print(f"[展开] 页面上无「{title}」标题，跳过。", flush=True)
                    continue
                await link.first.scroll_into_view_if_needed(timeout=10_000)
                await link.first.click(timeout=15_000)
                await page.wait_for_timeout(350)
                print(f"[展开] 已对「{title}」执行点击。", flush=True)
            except (PlaywrightTimeoutError, PlaywrightError):
                print(f"[展开] 点击「{title}」失败，继续下一项。", flush=True)
                continue

    await page.wait_for_timeout(500)
    print("[展开] 等待 Work Location 等区块加载（若页面无该节则跳过）…", flush=True)

    try:
        await page.wait_for_function(
            """() => {
          const h = Array.from(document.querySelectorAll('a.inspira-accordion-header'))
            .find(a => (a.innerText||'').trim() === 'Work Location');
          if (!h) return true;
          let n = h.nextElementSibling;
          while (n && !(n.innerText||'').trim()) n = n.nextElementSibling;
          return !!(n && (n.innerText||'').trim().length > 0);
        }""",
            timeout=12_000,
        )
    except PlaywrightTimeoutError:
        print("[展开] 等待 Work Location 正文超时（可能该岗位无此节），继续。", flush=True)

    print("[展开] 折叠展开流程结束。接下来将运行 EXTRACT_SCRIPT。", flush=True)


def _field_missing(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, str) and not val.strip():
        return True
    return False


def _print_yellow_warning(msg: str) -> None:
    """在支持 ANSI 的终端中显示黄色醒目警告（Windows 终端 / 常见 Linux / macOS）。"""
    yellow = "\033[93m"
    reset = "\033[0m"
    print(f"{yellow}{msg}{reset}", flush=True)


async def _fetch_one_detail(page: Page, url: str) -> dict[str, Any]:
    print(f"\n[页面] 正在加载: {url}", flush=True)
    # 不用 networkidle：SPA 可能长期有连接，导致 wait_for_load_state 挂起
    await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    await page.wait_for_timeout(1500)
    print("[页面] 等待职位标题 (h1) 可见…", flush=True)
    await page.locator("h1").first.wait_for(state="visible", timeout=60_000)

    await _expand_job_page(page)

    print("[提取] EXTRACT_SCRIPT 运行前：即将在页面内执行字段抽取脚本。", flush=True)
    data = await page.evaluate(EXTRACT_SCRIPT)
    assert isinstance(data, dict)
    print("[提取] EXTRACT_SCRIPT 运行完成，正在组装结果字典…", flush=True)

    job_title = data.get("job_title")
    gbd = data.get("gray_box_details")
    work_location = data.get("work_location")
    expected_duration = data.get("expected_duration")
    resp_raw = data.get("responsibilities_raw")
    qual_raw = data.get("qualifications_raw")

    gray_box_details: Optional[dict[str, Any]] = None
    if isinstance(gbd, dict):
        gray_box_details = {
            "duty_station": gbd.get("duty_station"),
            "department_office": gbd.get("department_office"),
            "deadline": gbd.get("deadline"),
        }

    full_block = _merge_full_description(
        resp_raw if isinstance(resp_raw, str) else None,
        qual_raw if isinstance(qual_raw, str) else None,
    )

    out = {
        "job_title": job_title if isinstance(job_title, str) else None,
        "gray_box_details": gray_box_details,
        "work_location": work_location if isinstance(work_location, str) else None,
        "expected_duration": expected_duration
        if isinstance(expected_duration, str)
        else None,
        "full_description_block": full_block,
        "original_url": url,
        "error": None,
    }

    if not _field_missing(out.get("job_title")):
        print(f'[提取] 已成功提取 Job Title: {out["job_title"][:120]}{"…" if len(out["job_title"] or "") > 120 else ""}', flush=True)
    else:
        print("[提取] Job Title 为空或未取到。", flush=True)

    gbd = out.get("gray_box_details")
    if isinstance(gbd, dict) and not _field_missing(gbd.get("deadline")):
        print(f'[提取] 已成功提取 Deadline（自灰框）: {gbd.get("deadline")}', flush=True)
    else:
        print("[提取] Deadline（灰框）为空或未取到。", flush=True)

    if isinstance(gbd, dict):
        if not _field_missing(gbd.get("duty_station")):
            print(f'[提取] 已成功提取 Duty Station: {gbd.get("duty_station")}', flush=True)
        if not _field_missing(gbd.get("department_office")):
            print(
                f'[提取] 已成功提取 Department/Office: {gbd.get("department_office")}',
                flush=True,
            )

    if not _field_missing(out.get("work_location")):
        print(f'[提取] 已成功提取 Work Location: {out["work_location"]}', flush=True)
    if not _field_missing(out.get("expected_duration")):
        print(f'[提取] 已成功提取 Expected Duration: {out["expected_duration"]}', flush=True)

    if not _field_missing(out.get("full_description_block")):
        blen = len(out["full_description_block"] or "")
        print(f"[提取] 已成功提取 full_description_block（长度 {blen} 字符）。", flush=True)
    else:
        print("[提取] full_description_block 为空。", flush=True)

    return out


async def fetch_job_details(urls: list[str]) -> list[dict[str, Any]]:
    """
    异步访问每个详情页，展开折叠后抓取字段，返回字典列表。
    单条失败不中断，失败项带 error 与 original_url。
    """
    results: list[dict[str, Any]] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=_playwright_headless_from_env(),
            slow_mo=_playwright_slow_mo_ms(),
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
                total = len(urls)
                for i, url in enumerate(urls):
                    print(
                        f"\n========== [{i + 1}/{total}] 开始处理 ==========",
                        flush=True,
                    )
                    if i > 0:
                        print("[进度] 请求间隔 1–2 秒随机延迟…", flush=True)
                        await _delay_between_requests()
                    url = (url or "").strip()
                    if not url:
                        results.append(
                            {
                                "job_title": None,
                                "gray_box_details": None,
                                "work_location": None,
                                "expected_duration": None,
                                "full_description_block": None,
                                "original_url": url,
                                "error": "empty url",
                            }
                        )
                        continue
                    try:
                        row = await _fetch_one_detail(page, url)
                        results.append(row)
                        print(
                            f"[进度] 第 {i + 1}/{total} 条处理完毕（error={row.get('error')}）。",
                            flush=True,
                        )
                    except PlaywrightTimeoutError as e:
                        print(
                            f"[超时] {url}\n{e}",
                            file=sys.stderr,
                        )
                        results.append(
                            {
                                "job_title": None,
                                "gray_box_details": None,
                                "work_location": None,
                                "expected_duration": None,
                                "full_description_block": None,
                                "original_url": url,
                                "error": f"timeout: {e}",
                            }
                        )
                    except (PlaywrightError, Exception) as e:
                        print(
                            f"[失败] {url}\n{e}",
                            file=sys.stderr,
                        )
                        traceback.print_exc()
                        results.append(
                            {
                                "job_title": None,
                                "gray_box_details": None,
                                "work_location": None,
                                "expected_duration": None,
                                "full_description_block": None,
                                "original_url": url,
                                "error": f"{type(e).__name__}: {e}",
                            }
                        )
            finally:
                await context.close()
        finally:
            await browser.close()

    return results


# 示例：两条真实详情页（可将 crawler 输出的 20 条 URL 粘贴至此或自行传入 fetch_job_details）
SAMPLE_DETAIL_URLS: list[str] = [
    "https://careers.un.org/jobSearchDescription/272640?language=en",
    "https://careers.un.org/jobSearchDescription/275393?language=en",
]


def main() -> None:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # 默认只跑前 2 条，便于调试；完整跑法：fetch_job_details(SAMPLE_DETAIL_URLS) 或传入 crawler 的 20 条 URL
    test_urls = SAMPLE_DETAIL_URLS[:2]
    print(
        f"[main] 本次测试 URL 数量: {len(test_urls)}（默认取 SAMPLE_DETAIL_URLS 前 2 条）\n",
        flush=True,
    )

    rows = asyncio.run(fetch_job_details(test_urls))

    with open(RESULTS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=4)
    print(
        f"\n[main] 结果已保存: {RESULTS_JSON_PATH}（UTF-8，indent=4）\n",
        flush=True,
    )

    print("[main] 完整性检查（job_title / deadline / full_description_block）…", flush=True)
    for r in rows:
        url = (r.get("original_url") or "").strip() or "(无 URL)"
        gbd = r.get("gray_box_details")
        deadline_val: Any = None
        if isinstance(gbd, dict):
            deadline_val = gbd.get("deadline")
        missing: list[str] = []
        if _field_missing(r.get("job_title")):
            missing.append("job_title")
        if _field_missing(deadline_val):
            missing.append("deadline")
        if _field_missing(r.get("full_description_block")):
            missing.append("full_description_block")
        if missing:
            _print_yellow_warning(
                f"[完整性警告] 以下字段为空或缺失: {', '.join(missing)} | URL: {url}"
            )

    first_ok: Optional[dict[str, Any]] = None
    for r in rows:
        if r.get("error") is None:
            first_ok = r
            break

    print("\n[main] 第一条成功抓取记录的完整字典（供核对）:\n", flush=True)
    if first_ok is not None:
        print(json.dumps(first_ok, ensure_ascii=False, indent=2))
    else:
        print("没有成功抓取的岗位（请检查网络或 URL）。", file=sys.stderr)


if __name__ == "__main__":
    main()
