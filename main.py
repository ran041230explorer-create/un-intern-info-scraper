"""
联合国实习岗位流水线总控：日期 → 列表 URL → 详情抓取 → 断点 raw_data.json → AI 生成文档。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import ai_processor
import crawler
import date_logic
import detail_fetcher

LOG = logging.getLogger("un.pipeline")

RAW_DATA_JSON_PATH = os.getenv("RAW_DATA_JSON_PATH", "raw_data.json")


def _configure_stdio_utf8() -> None:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


async def run_pipeline() -> None:
    _configure_stdio_utf8()
    _configure_logging()

    LOG.info("流水线启动。")

    ai_processor.configure_runtime_networking()
    if ai_processor.is_github_actions_environment():
        LOG.info("检测到 GITHUB_ACTIONS，跳过本地代理注入。")
    elif ai_processor.ACTIVE_HTTP_PROXY_URL:
        LOG.info("已根据环境配置 HTTP 代理（Gemini / httpx 使用）。")
    else:
        LOG.info("未配置 HTTP 代理（本地可在 .env 设置 UN_HTTP_PROXY 或 HTTP_PROXY）。")

    today = date_logic.get_pipeline_today()
    LOG.info("阶段 A：当前流水线日期为 %s。", today.isoformat())

    urls = await crawler.fetch_candidate_urls(simulated_today=today)
    LOG.info("阶段 B：列表抓取完成，候选 URL 数量=%d。", len(urls))
    if not urls:
        LOG.error("无候选 URL，流水线终止。")
        return

    details = await detail_fetcher.fetch_job_details(urls)
    LOG.info("阶段 C：详情抓取完成，记录数=%d。", len(details))

    raw_path = Path(RAW_DATA_JSON_PATH)
    raw_path.write_text(
        json.dumps(details, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    LOG.info("断点：详情已写入 %s（绝对路径 %s）。", raw_path, raw_path.resolve())

    LOG.info("阶段 D：开始 AI 处理与 Word 导出…")
    summary = await ai_processor.run_ai_processing(
        details,
        meta_input_label=str(raw_path.resolve()),
    )
    LOG.info(
        "阶段 D 完成：成功 %d 条，失败 %d 条；JSON=%s；Word=%s（已写入=%s）。",
        len(summary.get("results", [])),
        len(summary.get("failures", [])),
        summary.get("output_json_path"),
        summary.get("output_docx_path"),
        summary.get("docx_written"),
    )
    LOG.info("流水线全部结束。")


def main() -> None:
    try:
        asyncio.run(run_pipeline())
    except RuntimeError as e:
        LOG.error("%s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
