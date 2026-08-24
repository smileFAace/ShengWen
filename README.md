# 声文智汇（ShengWen）- Agent驱动的长视频总结工作流

<p align="center">
  <img src="prj-docs/images/web-wide.png" alt="最终生成图片预览" width="900">
  <br>
</p>

<p align="center">
  <strong>界面展示（将本地考试复习资料总结成文）</strong>
</p>

<p align="center">
  <a href="#快速部署"><img src="https://img.shields.io/badge/Version-v0.1.3-orange.svg?style=for-the-badge" alt="Version v0.1.3"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPL%20v3-blue.svg?style=for-the-badge" alt="GPL v3 License"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.10+-blue.svg?style=for-the-badge" alt="Python 3.10+"></a>
  <a href="https://vuejs.org/"><img src="https://img.shields.io/badge/Vue-3.x-green.svg?style=for-the-badge" alt="Vue 3"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.100+-teal.svg?style=for-the-badge" alt="FastAPI"></a>
</p>

> **数小时的视频课程，几倍速刷完还是很累？**
> **AI总结工具只给你一个大纲，细节全丢了？**
> **想要的是详实的笔记，而不是概略的摘要？**

**声文智汇（ShengWen）** 就是为了解决这些问题而生的。

---

## 💡 为什么做这个项目

作为一个经常刷教学视频的学习者，我发现：

- 📹 **动辄几小时的课程视频**，倍速观看很累，走神现象经常发生
- 📝 **现有的AI总结工具**只能生成"大纲式"的概略总结，细节全丢了
- 🤖 **即使是长上下文模型**（如Gemini 2.5 Pro），面对超长视频也会"注意力涣散"

于是我做了ShengWen，核心创新是**智能上下文技术**：

> 💡 **就像旧时代需要管理内存一样，AI时代需要管理AI上下文**

- 让每个LLM不仅处理当前分块，还能智能地将关键信息传递给下一个LLM
- 程序固有部分确保总结风格一致，LLM智能传递部分保留关键细节
- 最终实现：**将视频总结为结构丰富、细节完整的流畅文章**

现在对于长视频——不管是中文还是外文——可一键变成详实的中文学习笔记。


---

## 🎯 适合谁用

**如果你是**：

- 📚 **大学生/研究生**：需要刷大量课程视频、学术讲座，做笔记备考
- 🌍 **自学者**：经常看各种教学视频，希望转化为中文笔记
- ✍️ **内容创作者**：需要快速了解视频内容，转化为文章素材
- 💼 **职场人士**：需要将会议录音、培训视频转化为文字记录

这**就是**你要找的工具。


---



## 核心特性

### **1. 智能总结引擎 🤖**

采用创新的上下文管理技术，让 AI 在处理长视频时既保持结构一致性，又能保留关键细节。

**标准模式**：
- 基于精心调试的提示词与总结流程
- 适合绝大多数视频场景（建议40分钟-1小时以内）
- 在信息密度、可读性和结构化表达之间做平衡

**Agent 增强模式**（✅ 已实现）：
- 🎯 适合超长视频（1小时以上）
- 🔥 解决长文本处理时的细节丢失问题
- ✨ 智能传递关键信息，确保总结完整性
  - 就像管理内存一样管理AI上下文，实现跨分块总结而保持文章流畅完整
- 📊 **效果对比**：
  - **⬇️点击查看对比**（均由 Gemini 2.5 Pro + tiny 转录模型生成）
  - [🙂标准模式总结结果](prj-docs/长视频总结-非agent.md) vs **[😄Agent 增强模式总结结果](prj-docs/长视频总结-带agent.md)**
  - 测试视频：[《如何像高级工程师一样设计API？REST、GraphQL、认证与安全核心要点》(时长01:23:21)](https://www.bilibili.com/video/BV16wZKBbEbd)
  - **Agent增强模式**：细节更丰富，更像是一篇详实的完整文章
- ⚙️ **使用方式**：
  - 在前端页面"开始处理"按钮上方，通过滑块切换标准/Agent模式
  - 也可在前端设置中选择自动模式（按视频长度自动选择总结策略）

### **2. 丰富输出 📊**

**时间戳跳转**（仅支持 Bilibili）：
- ✅ 阅读文章时点击时间戳 → 直接跳转 B 站视频对应位置
- 方便复习重点内容

**文章大纲导航**：
- ✅ 自动提取Markdown标题生成章节导航
- 支持快速跳转到文章任意章节
- 实时高亮当前阅读位置

**Mermaid 图表**：
- 自动生成流程图、思维导图
- 可视化视频内容结构

**一键成图导出**：


<p align="center">
  <img src="prj-docs/images/picture-worker.png" alt="最终生成图片预览" width="900">
  <br>
</p>

- **成图工作台**：支持先预览再导出，避免反复试错
  - 可调输出宽度、页面比例（如 9:64 超长图）
  - 可配置元信息显示策略（如仅首图显示）
  - 可选编码格式（JPEG 推荐）、渲染精度
  - 支持压缩质量、字体缩放、间距缩放微调，兼顾清晰度与体积
  - 右侧实时预览最终排版效果和文件体积，用于分享与归档

### **3. 可追溯性 🔗**

- 每个总结都包含**原视频链接**和**UP主主页链接**
- 方便回溯原始内容和原作者

### **4. 多任务管理 🧾**

- 进度条实时显示任务状态
- 任务元数据、视频链接可追溯
- 支持任务处理流水线（下载 → 转录 → 摘要）
- **文件管理系统**：嵌套文件夹组织、拖拽移动、B站多P视频自动建文件夹

### **5. Profile 配置系统 ⚙️**

- 支持创建多个独立的 LLM 配置（Profile），每个配置有名称、供应商、模型等
- 一键切换活跃配置，无需重新输入 API Key
- 内置 OpenAI / DeepSeek / OpenRouter / Ollama 等供应商预设，自动填入默认值
- 同一中转站可创建多个 Profile 分别对应不同模型

### **6. 音视频支持 🎬**

- **Bilibili直链转换**：支持B站视频一键下载
- **本地文件上传**：支持本地音频/视频文件
- **字幕/文稿直读**：支持直接上传字幕文件（`.srt` / `.vtt` / `.ass` / `.ssa`）或纯文本文稿（`.txt`），跳过语音识别直接进入 AI 总结

当前版本对本地文件采用**扩展名白名单校验**，支持如下格式：

- 视频：`.mp4`、`.avi`、`.mov`、`.mkv`、`.flv`、`.wmv`、`.webm`、`.m4v`
- 音频：`.mp3`、`.wav`、`.flac`、`.aac`、`.ogg`、`.m4a`、`.wma`、`.opus`
- 字幕/文稿：`.srt`、`.vtt`、`.ass`、`.ssa`、`.txt`

#### **6. CPU 友好 + GPU 加速 ⚡**
默认即开即用的 `CPU` 转录体验，同时提供可切换的 `CUDA` 加速路径：

- **CPU 开箱可用**：默认 `tiny + CPU`，在 i7-12700 上实测约 `10x` 识别倍率（具体耗时与音频质量、模型大小有关）
- **CUDA 智能诊断**：自动检测 `NVIDIA / PyTorch CUDA / CTranslate2` 状态；可用时启用 GPU 转录，不可用时给出原因与处理建议
- **字幕优先，回退语音识别**：可开启”优先使用字幕”，未获取到字幕时自动回退到本地语音识别

<p align="center">
  <img src="prj-docs/images/subtitle.png" alt="转录设置" width="600">
  <br>
</p>

**如何启用CUDA加速**：

1. **确认硬件**：需要NVIDIA显卡（支持CUDA）

2. **安装CUDA Toolkit**：
   - 下载地址：https://developer.nvidia.com/cuda-downloads
   - 推荐版本：CUDA 11.8 或 12.x

3. **安装PyTorch（CUDA版本）**：
   ```bash
   # CUDA 11.8
   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

   # CUDA 12.x
   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
   ```

4. **在前端切换到CUDA模式**：
   - 打开”转录设置”，将”设备”从`cpu`切换为`cuda`，保存配置

**CUDA加速效果**：
- 相比起 CPU ，转录速度可提升 3-10 倍（取决于显卡性能）
- 推荐显存：4GB以上（tiny/base模型），8GB以上（medium/large模型）

#### **7. PC / 手机端Web阅读支持 📱**
宽屏/窄屏自适应布局，良好阅读体验


---
## 🧭 导航

- [核心特性](#核心特性)
- [快速部署](#快速部署)
- [配置系统](#配置系统)
- [常见 Q&A](#常见-qa)
- [TODO / 后续计划](#todo--后续计划)
- [贡献](#-贡献)
- [许可证](#-许可证)
- [致谢](#-致谢)

---
## 💿 快速部署

### 推荐方式：使用 AI Coding Agent 部署 🤖

如果你使用 Claude Code、OpenCode、Cursor、Trae 等 AI coding agent，可以直接让它阅读本项目的 README 文件并自动完成部署：

**示例提示词：**
```
请阅读这个项目的 README.md，然后帮我完成部署
```

AI agent 会尝试：
- 理解项目结构和依赖
- 执行前端构建和后端依赖安装
- 处理可能遇到的问题
- 启动服务

给 Agent 的提示词：
```
如果你是 AI Agent，请按以下步骤帮助用户完成部署：

1. **检测操作系统**：判断是 Linux/macOS 还是 Windows
2. **运行部署脚本**（不要自己写命令，使用现有脚本）：
   - Linux/macOS: `chmod +x deploy一键部署.sh && ./deploy一键部署.sh`
   - Windows: `deploy一键部署.bat`
3. **等待部署完成**：脚本会自动完成环境检查、依赖安装、前端构建
4. **运行启动脚本**（不要自己写命令，使用现有脚本）：
   - Linux/macOS: `chmod +x run一键启动.sh && ./run一键启动.sh`
   - Windows: `run一键启动.bat`
5. **确认服务启动**：看到 "🚀 服务启动完成" 提示后，告知用户访问 http://localhost:8000

**重要**：
- 不要尝试手动执行 `pip install` 或 `npm install`，脚本已包含这些步骤
- 不要修改脚本内容，除非遇到明确的错误
- 如果部署脚本报错，先阅读错误信息，再决定是否需要手动干预
- 配置文件（LLM API Key 等）可以在服务启动后通过前端设置面板配置

**常见问题处理**：
- 如果提示 Node.js 版本过低：建议用户升级到 Node.js 20+
- 如果提示 Python 版本过低：建议用户升级到 Python 3.10+，但也不建议使用太新的版本
- 如果前端构建失败：检查 npm 是否正常，必要时清理 `frontend/node_modules` 后重试
- 如果启动时提示缺少 `frontend/dist`：重新运行部署脚本
```


---

### 一键部署脚本

**Linux/macOS:**
```bash
chmod +x deploy一键部署.sh
./deploy一键部署.sh
```

**Windows:**
```cmd
deploy一键部署.bat
```

或者双击运行 `deploy一键部署.bat`

脚本会自动完成：
1. 检查 Node.js/Python 版本（前端构建需要 Node 20+，后端需要 Python 3.10+）
2. 在 Linux 下尝试补齐系统依赖（`ffmpeg` / `git` / `python3-venv`，仅在需要时调用 sudo）
3. 创建并复用项目虚拟环境 `.venv`
4. 安装前端依赖并构建（自动处理 lockfile/代理/前端目录权限异常）
5. 安装 Python 后端依赖

**注意**：
- **不要用 `sudo` 直接运行部署脚本，也不要用 `sudo npm`。**请始终用普通用户运行 `./deploy一键部署.sh`。
- 部署脚本不会自动启动服务，需要手动运行启动命令
- 如果项目有更新，执行 `git pull` 后需要重新运行部署脚本以更新依赖和前端构建

### 你也可手动部署

#### Linux/macOS 手动部署
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt

cd frontend
npm ci --no-audit --fund=false
npm run build
cd ..
```

#### Windows 手动部署
```cmd
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
cd frontend
npm ci --no-audit --fund=false
npm run build
cd ..
```

### 配置（推荐前端设置）


推荐做法：启动后直接通过前端设置面板配置 LLM 与转录参数，无需手动编辑 JSON。

如果你希望手动维护配置文件，也可以创建：

```bash
cp config/settings.example.json config/settings.json
# Windows 可用: copy config\\settings.example.json config\\settings.json
```

按需编辑 `config/settings.json` 即可。

**提示**：前端设置是主要入口；手动编辑配置文件仅作为高级/可选方式。

### 启动服务

**run一键启动（Linux/macOS）：**
```bash
chmod +x run一键启动.sh
./run一键启动.sh
```

**一键启动（Windows）：**
```cmd
run一键启动.bat
```
或者双击运行 `run一键启动.bat`

**手动启动：**
若一键启动遇到问题，也可尝试手动启动：
```bash
# Linux/macOS（若使用 deploy 脚本安装）
source .venv/bin/activate
python ShengWen-app.py
```

```bash
# Windows
.\.venv\Scripts\python.exe ShengWen-app.py
```
请注意使用创建的虚拟环境中的 python 来启动，否则可能缺少依赖而报错

### 成功启动提示参考
```bash
========================================
  声文智汇 (ShengWen) - 一键启动
========================================

使用 Python: D:\prj\SonicScribe\.venv\Scripts\python.exe

INFO  2026-03-13 10:13:01.248 Using SQLite database: ShengWen.db
INFO  2026-03-13 10:13:03.422 --- [Startup] 未检测到代理环境，已自动接管本地代理端口 7890 ---
INFO  2026-03-13 10:13:03.429 ╔════════════════════════════════════════════════════════════╗
INFO  2026-03-13 10:13:03.429 ║  声文智汇 ShengWen v0.1.3                           ║
INFO  2026-03-13 10:13:03.429 ╚════════════════════════════════════════════════════════════╝
INFO:     Started server process [22792]
INFO:     Waiting for application startup.
INFO  2026-03-13 10:13:03.588 --- [Lifespan] 服务启动完成，前端已可访问 ---
INFO  2026-03-13 10:13:03.589 --- [Lifespan] Workers 将在首次使用时自动初始化 ---
INFO  2026-03-13 10:13:03.595 ╔════════════════════════════════════════════════════════════╗
INFO  2026-03-13 10:13:03.596 ║  🚀 服务启动完成，可通过浏览器访问：                       ║
INFO  2026-03-13 10:13:03.596 ╠════════════════════════════════════════════════════════════╣
INFO  2026-03-13 10:13:03.596 ║  📱 本机访问:  http://localhost:8000/
INFO  2026-03-13 10:13:03.596 ║  🌐 局域网访问: http://192.168.0.45:8000/
INFO  2026-03-13 10:13:03.596 ╚════════════════════════════════════════════════════════════╝
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     ('127.0.0.1', 51382) - "WebSocket /ws" [accepted]
INFO:     connection open
```

- 启动后本机即可在浏览器通过 `localhost:<端口号>` 访问
- 局域网内的其它设备即可通过 `<服务器局域网IP>:<端口号>` 访问

---

## ⚙️ 配置系统

ShengWen 当前版本以 **前端设置面板** 作为主要配置入口，同时保留 JSON 文件供手动维护：

- 推荐入口：前端设置面板（`LLM` / `转录设置`）
- 配置文件：`config/settings.json`
- 如需手动维护，可先从 `config/settings.example.json` 复制一份

---

### 配置示例

```json
{
  "whisper": {
    "model_path": "E:/models/faster-whisper/tiny",
    "model_size": "tiny",
    "device": "cpu",
    "enable_bilibili_subtitle_fetch": true,
    "bilibili_sessdata": ""
  },
  "llm": {
    "profiles": [
      {
        "id": "default",
        "name": "DeepSeek V4",
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "api_key": "your_api_key",
        "model_id": "deepseek-v4-flash",
        "temperature": 0.7,
        "context_window_size": 1000000
      }
    ],
    "active_profile_id": "default"
  }
}
```

### B 站字幕直取与 Cookie 来源

- 当开启 `enable_bilibili_subtitle_fetch` 时，B 站任务会优先尝试直取字幕，失败自动回退到下载+ASR。
- `SESSDATA` 来源优先级为：
  1. 全局配置（可在前端转录设置面板中维护）
  2. 环境变量（`BILIBILI_SESSDATA` / `SESSDATA`）
- 前端仅显示掩码值与来源，不显示明文。


---
## 🤔 常见 Q&A

**刚部署下来不会用？先看**：[使用说明](prj-docs/使用说明.md)

### Q1. 怎么用转录模型？

首次启动时，转录模型会自动联网下载；网络不通时任务可能无法正常开始。也可先准备好本地模型，再让 ShengWen 直接读取本地文件夹。

| 模型档位 | 速度/资源占用 | 质量与适用场景 | 官方下载页 |
| :--- | :--- | :--- | :--- |
| **tiny** | 最快、最省资源 | 快速首选；转录精度有限，会有错字，但经 AI 总结后通常可读性仍然不错 | https://huggingface.co/Systran/faster-whisper-tiny |
| **base** | 快 | 比 tiny 更稳一点，适合希望更稳但仍追求速度的场景 | https://huggingface.co/Systran/faster-whisper-base |
| **small** | 中等 | 精度继续提升，适合日常较高质量转录 | https://huggingface.co/Systran/faster-whisper-small |
| **medium** | 偏慢、资源要求较高 | 精度更好，建议性能较好的电脑使用 | https://huggingface.co/Systran/faster-whisper-medium |
| **large-v3** | 最慢、资源占用最高 | 通常精度最好，适合对细节更敏感的离线批处理场景 | https://huggingface.co/Systran/faster-whisper-large-v3 |
- **如何配置模型：**

  1. **自动下载**（网络通畅时）：
     ```json
     {
       "whisper": {
         "model_size": "tiny"
       }
     }
     ```
     也可以改成 `base` / `small` / `medium` / `large`。

  2. **或本地配置**：
     ```json
     {
       "whisper": {
         "model_path": "E:/models/faster-whisper/tiny"
       }
     }
     ```
     一个可用的模型文件夹中通常包含（缺少其中文件时，模型通常无法被正确加载）：

     ```text
     E:/models/faster-whisper/tiny/
     ├─ config.json
     ├─ model.bin
     ├─ tokenizer.json
     └─ vocabulary.txt
     ```
- **高性能电脑建议：**  
  可以直接尝试 `small` / `medium` / `large`。若已准备好本地模型目录，可在前端“转录设置”中填写模型路径（`whisper.model_path`）。

### Q2. 我要选哪个 AI 模型来总结？

- 通常来说，本项目更加适合于**有思考能力的、上下文能力较好**的大语言 AI 模型，这会影响总结的结构性、细节保真和时间戳标注正确性性。
- 即使是同一篇文章、同一个模型，由于 LLM 模型生成的随机性，**最终总结质量会发生浮动**；对内容不满意 / 总结内容出错时可点击悬浮工具栏的 “AI 重新总结” 按钮进行**重新”抽卡”**

---

#### **一些大语言 AI 模型效果测试**

| 大语言 AI 模型 | 总结风格（实测） |  总结效果示例<br>（总结至 [@林亦LYi](https://space.bilibili.com/4401694/?spm_id_from=333.788.upinfo.detail.click) 的 [一个视频搞懂OpenClaw！](https://www.bilibili.com/video/BV1jEAaz3E6K)） |
| :--- | :--- | :--- | 
| **Gemini 2.5/3.0 Pro** | 上下文能力较好 + 带思考，原文细节较为丰富（个人最习惯用） | [点击查看示例图](prj-docs/images/llm-gemini-25pro-summary-20260301-1214.png) |
| **DeepSeek V4 Flash** | 输出迅速，性价比极高，长上下文天然适合该项目 | [点击查看示例图](prj-docs/images/llm-deepseek-v4flash-summary.png) |
| **GPT 4.1 / 5.x** | 细节丰富，有专业感 | [点击查看示例图](prj-docs/images/llm-gpt52-summary-20260301-1213.png) |
- 不同的模型会对最终总结文章的**风味造成影响**。
- 可尝试用同一视频分别交给不同 AI 模型总结后横向对比，选择最符合自己口味的模型。
- **模型风味测试实操**：
  - 选择一个已完成的任务，在前端设置好感兴趣的 AI 模型后点击悬浮工具栏的 “AI 重新总结” 按钮
  - 感受总结完成后的文章风格差异

### Q3. 这个项目的能力边界是什么？

#### 😄 适合
- 把公开视频/音频变成“可读文本 + AI 总结”
- 课程复盘、会议整理、个人知识归档

#### 😱 不适合
- 要求“每句话 100% 准确”的正式法律/医疗场景
- 需要实时字幕、同声传译、直播级低延迟
- 语音不清晰甚至无语音的视频

#### ❕ 使用建议
- 音频越清晰，转录越准；多人重叠说话、噪音大会影响准确率
- AI 总结是辅助阅读，重要结论请回看原文转录再确认
- 超长内容建议分段处理（当前版本建议单次 40-60 分钟内）
- 本地文件请优先使用 README 中列出的支持格式（尤其推荐 `.mp3` / `.wav` / `.mp4`）

---
## 🧾 TODO / 后续计划
- [x] ~~视频链接旁添加视频作者解析和显示~~（2026-03-01已实现）
- [x] ~~一键生图的预览、调整功能，使其更加适合调整 / 阅读 / 储存 / 传播~~（2026-03-03已实现）
- [x] ~~字幕文件直接获取 / 解析 / 降级~~（2026-03-04已实现）
- [x] ~~Agent 增强模式集成（长内容分段理解、跨段关联总结）~~（2026-03-07已实现）
- [x] ~~文章大纲导航（自动提取标题、快速跳转章节）~~（2026-03-07已实现）
- [x] ~~时间戳跳转（点击时间戳跳转视频对应时间点）~~（2026-03-08已实现）
- [ ] Docker部署支持
- [x] ~~支持处理字幕文件（`.srt` / `.ass` / `.vtt`）~~（2026-08-20已实现，含 `.ssa` / `.txt` 文稿直读）
- [ ] 英文语言支持（界面与提示）
- [ ] 增加agent模式下流水线处理（一遍转录一遍总结）
- [ ] 批量任务处理（批量链接、批量本地文件、带分 P 视频链接处理一键批量任务、批量导出总结文本等）
- [x] ~~更好的设置界面引导（Profile 配置系统、供应商预设自动填入）~~（2026-05-04已实现）
- [ ] 研究如何结合 AI 视觉能力，让总结中包含视频画面信息（如果研究出来了，我是不是可以把这个项目的名字从“**声文智汇**”改成“**声文视汇**”……？🤔）

---
## 💓 其它信息

- 本项目源于我自己的真实需求：刷教学视频太耗时，倍速观看很累，现有AI总结工具只给大纲不给细节
- 在开发过程中发现：即使是长上下文模型，面对超长视频也会"注意力涣散"，于是设计了智能上下文技术
- 将总结文本分享后发现受到欢迎，故决定发展成完整项目并开源
- 项目尚处于萌芽期，可能有疏忽和考虑不周全之处，**欢迎在 Issue 中反馈**
- 如果这个项目对你有帮助，请点个 ⭐️Star，你的反馈是我持续改进的动力！

---

## 📄 许可证

本项目采用 [GPL v3](LICENSE) 许可证。

---

## 🙏 致谢

### 技术依赖
- [faster-whisper](https://github.com/guillaumekln/faster-whisper) - 高性能语音转录引擎
- [litellm](https://github.com/BerriAI/litellm) - 统一 LLM 接口
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - 强大的视频下载工具
- [FastAPI](https://fastapi.tiangolo.com/) - 现代 Python Web 框架
- [Vue.js](https://vuejs.org/) - 渐进式 JavaScript 框架

### 特别鸣谢
- **[Linux Do 论坛](https://linux.do/)** - 感谢这个纯粹、高质量的技术社区，为独立开发者提供了真诚的反馈和支持。我相信开源项目的价值不仅在于代码，更在于背后的故事和社区的力量。


<div align="center">

---
**最后，如果觉得这个项目有用，请点个 ⭐️Star，大家的反馈是我持续改进的动力🥰~**

[⬆ 回到顶部](#️-声文智汇---ShengWen)

Made ❤️ by **[smileFAace](https://linux.do/u/smileface/summary)**

联系我: [smileFAace@outlook.com](mailto:smileFAace@outlook.com)

</div>

