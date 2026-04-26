[README.md](https://github.com/user-attachments/files/27093250/README.md)
# UN Intern Info Scraper | 联合国实习信息自动化整理系统

> Every two weeks, this system fetches UN internship postings, cleans & translates them with AI, exports a structured report, and emails it to the applicant.

## 这个项目的初衷 (Purpose)
- 过去的大半年里，定期翻译、整理、输出联合国实习信息是我在社团工作中最厌恶的事。<br>
- 在机械的复制粘贴与无止境的格式调整中，我总在想：人的时间与注意力怎能如此低贱呢？我们本应该去做那些创造性、高价值与高难度的事情，而不是在写字楼的“流水线”里浪费生命。<br>
- 感谢AI的出现，作为我最亲密的战友，是它让这个项目成为可能，让我将一腔怒火与愤懑转化为创造的力量，让我坚定地在人非工具的道路上继续前进。

这只是一个很小的实用性项目，但它却让我明白：  
**当你梦想登上月球时，再高的梯子也无济于事。<br> 但当你拥有一艘航空母舰时，任何更宏伟的梦想都值得一试。<br>
AI就是我的航空母舰。**

---

## 这个项目做了什么（Features）
- ⏱️ 每两周自动运行（GitHub Actions Schedule）
- 🌐 抓取联合国实习岗位列表与详情
- 🧠 使用 Gemini 对内容进行翻译与结构化整理（with失败补救策略）
- 📝 导出 Word 报告（统一字段与排版）
- 📧 自动邮件发送到指定收件箱
- 🔐 全程使用环境变量与 GitHub Secrets 管理敏感信息（无硬编码）

---

## 系统流程（Pipeline）
1. data_logic.py: 编写日期处理与过滤逻辑
2. crawler.py: 官网列表页爬取与随机抽样
3. detail_fetcher.py: 实习链接详情页信息抓取
4. ai_processor.py: 借助LLM提取关键信息与翻译 + 调整格式并输出word
5. send_email: 自动化运行 + 定时将结果发送至个人邮箱

---

## 技术实现亮点（Design highlights）
- **可复现**：保留原始抓取结果作为断点，便于调试与回放  
- **稳定性策略**：Flash 主模型 + Flash-Lite 补救，降低失败率  
- **安全**：敏感信息只存在 `.env` / GitHub Secrets，从不进入仓库  
- **可维护**：模块化拆分（crawler / fetcher / ai_processor / email）

---

## 快速开始（Quickstart）

### 1) 环境准备
- Python 3.10+
- Playwright (Chromium)

### 2) 安装依赖
```bash
pip install -r requirements.txt
python -m playwright install --with-deps chromium
```

### 3) 配置环境变量
创建一份 `.env`，填入：
- `GEMINI_API_KEY`
- `EMAIL_USER`
- `EMAIL_PASS`

### 4) 运行
```bash
python main.py
```

---

## GitHub Actions 自动运行（Optional）
在仓库 Settings → Secrets and variables → Actions 中添加：
- `GEMINI_API_KEY`
- `EMAIL_USER`
- `EMAIL_PASS`

Workflow：`.github/workflows/auto_run.yml`

---

## 合规声明（Disclaimer）
本项目仅用于个人学习与研究，禁止任何非法或商业目的。<br>
爬取UN Careers中的实习信息是为了制作宣传推文，吸引更多学生申请联合国实习，为国际发展与全球治理贡献力量。<br>
使用者应遵守目标网站的条款与 robots.txt，并控制抓取频率。由使用者行为造成的任何风险由使用者自行承担。

---

## 关于我（About me）
- Always be useful, always.
- 在科技与人文的交汇处，成为一名对人类有用的创造者，并始终对不可能之事抱有健康的漠视。
- 我正在思考的事：人工智能时代的Adwords会是怎样的？AI产业的飞轮效应会是怎样的？


如果你对这个项目或合作感兴趣，欢迎联系我：
- GitHub: @ran041230explorer-create
- Email: ran_041230@qq.com
