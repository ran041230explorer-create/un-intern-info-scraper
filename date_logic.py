"""
UN Careers 爬取脚本 — 日期处理：判断爬取日与截止日期过滤。
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Optional


def get_pipeline_today() -> date:
    """
    流水线使用的「当前日期」：默认系统当天；
    若设置环境变量 ``PIPELINE_SIMULATED_DATE=YYYY-MM-DD``（如测试），则使用该日期。
    """
    raw = (os.getenv("PIPELINE_SIMULATED_DATE") or "").strip()
    if not raw:
        return date.today()
    return date.fromisoformat(raw)


def is_scrape_day(today: Optional[date] = None) -> bool:
    """
    判断「今天」是否为每月固定爬取日：12 日或 27 日。

    :param today: 可选，用于测试注入；默认使用系统当天日期。
    """
    d = today if today is not None else date.today()
    return d.day in (12, 22,27)


def _parse_un_date(s: str) -> date:
    """解析官网截止日期，格式如 'Apr 17, 2026'。"""
    return datetime.strptime(s.strip(), "%b %d, %Y").date()


def should_keep_deadline(deadline_str: str, today: Optional[date] = None) -> bool:
    """
    根据爬取日规则，判断该截止日期是否应保留。

    - 若「今天」是当月 12 日：截止日期在当月 20 日（含）及之前的岗位返回 False。
    - 若「今天」是当月 27 日：截止日期在次月 7 日（含）及之前的岗位返回 False。
    - 若「今天」不是 12 日或 27 日：不做过滤，一律返回 True。

    :param deadline_str: 官网日期字符串，如 'Apr 17, 2026'
    :param today: 可选；为 None 时使用 ``date.today()``，也可传入虚拟日期做测试。
    :return: True 表示保留，False 表示过滤掉。
    """
    d = date.today() if today is None else today
    deadline = _parse_un_date(deadline_str)

    if d.day == 12:
        cutoff = date(d.year, d.month, 20)
        return deadline > cutoff
    if d.day == 27:
        if d.month == 12:
            cutoff = date(d.year + 1, 1, 7)
        else:
            cutoff = date(d.year, d.month + 1, 7)
        return deadline > cutoff
    return True


if __name__ == "__main__":
    import unittest

    class TestDateLogic(unittest.TestCase):
        def test_is_scrape_day(self):
            self.assertTrue(is_scrape_day(date(2026, 4, 12)))
            self.assertTrue(is_scrape_day(date(2026, 4, 27)))
            self.assertFalse(is_scrape_day(date(2026, 4, 11)))
            self.assertFalse(is_scrape_day(date(2026, 4, 13)))

        def test_day_12_filter(self):
            t = date(2026, 4, 12)
            self.assertFalse(should_keep_deadline("Apr 20, 2026", t))
            self.assertFalse(should_keep_deadline("Apr 10, 2026", t))
            self.assertTrue(should_keep_deadline("Apr 21, 2026", t))
            self.assertTrue(should_keep_deadline("May 1, 2026", t))

        def test_day_27_filter(self):
            t = date(2026, 4, 27)
            self.assertFalse(should_keep_deadline("May 7, 2026", t))
            self.assertFalse(should_keep_deadline("May 1, 2026", t))
            self.assertTrue(should_keep_deadline("May 8, 2026", t))
            self.assertTrue(should_keep_deadline("Jun 1, 2026", t))

        def test_day_27_december_rollover(self):
            t = date(2026, 12, 27)
            self.assertFalse(should_keep_deadline("Jan 7, 2027", t))
            self.assertTrue(should_keep_deadline("Jan 8, 2027", t))

        def test_non_scrape_day_keeps_all(self):
            t = date(2026, 4, 15)
            self.assertTrue(should_keep_deadline("Jan 1, 2020", t))

        def test_today_defaults_to_real_today(self):
            # 仅验证可调用；不断言具体布尔值（依赖运行日）
            should_keep_deadline("Jan 1, 2099", None)

    unittest.main(verbosity=2)
