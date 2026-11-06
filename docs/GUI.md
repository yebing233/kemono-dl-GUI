# kemono-dl GUI 使用说明

一个本地运行的现代化图形界面，覆盖 `kemono-dl` 命令行里的**全部**参数。
界面本身只做两件事：把你的选择翻译成真实的 `kemono-dl` 参数，然后把真实的
下载进程跑起来 —— 所以命令行有什么能力，界面就有同样的能力，输出、日志、行为
完全一致。

![界面结构](#界面结构) · [免安装使用](#方式一便携版推荐无需-python) · [源码运行](#方式二源码运行) · [功能对照表](#命令行参数--界面位置对照表)

---

## 三种打开方式

### 方式一：便携版（推荐，无需 Python）

下载 / 拿到 `dist\kemono-dl-gui.exe` 后**直接双击**即可：

* 不需要安装 Python，不需要 pip，不需要命令行；
* exe 内部打包了完整的 CPython 运行时、`requests` 和 `kemono_dl` 本身；
* 双击后会自动打开浏览器窗口（默认 `http://127.0.0.1:8765/`）；
* 用完想退出：点左侧栏底部的 **退出程序**（红色电源图标），浏览器里会显示
  「已退出」提示页，后台进程同时结束 —— 只关掉浏览器标签页**不会**停止服务。

> 首次运行时 Windows 可能弹出「已保护你的电脑」提示（未签名的自制程序常见），
> 点「更多信息」→「仍要运行」即可。程序只监听本机回环地址，不会对外开放端口。

### 方式二：源码运行

```bash
# 安装依赖（只需一次）
pip install -r requirements.txt

# 启动界面
python -m kemono_dl_gui
```

Windows 用户也可以双击项目根目录的 `启动 GUI.bat`（脚本会自动寻找 `py -3` 或 `python`）。

可用参数：

| 参数 | 说明 |
| --- | --- |
| `--host` | 监听地址，默认 `127.0.0.1`（仅本机访问，不建议改） |
| `--port` | 监听端口，默认 `8765`，写 `0` 表示自动挑一个空闲端口 |
| `--no-browser` | 启动后不自动打开浏览器 |

### 方式三：pip 安装后使用命令

```bash
pip install .
kemono-dl-gui        # 等同于 python -m kemono_dl_gui
```

---

## 界面结构

```
┌──────────┬─────────────────────────────────────┬──────────────────────┐
│ 左侧导航  │ 中间：参数表单                        │ 右侧：任务队列与日志    │
│ 链接      │  链接 / 批次文件 / 收藏下载            │  任务列表（串行队列）  │
│ 保存位置  │  保存路径 / 子目录结构                 │  进度条 / 速度 / ETA   │
│ 命名模板  │  模板预设 / 分段模板 / 自定义变量       │  实时日志（可保存）     │
│ 过滤      │  日期过滤 / 跳过扩展名 / 归档           │  停止 / 重试 / 打开目录 │
│ 账号      │  cookies / 三个站点登录                │                        │
│ 任务日志  │                                       │                        │
└──────────┴─────────────────────────────────────┴──────────────────────┘
                 底部固定操作栏：命令行预览 · 复制命令 · 开始下载
```

* 右上角可切换**深色 / 浅色**主题，选择会自动记住；
* 底部会实时显示即将执行的完整命令行（密码显示为 `******`），点「复制命令」
  就能拿到一条可以贴到终端里直接跑的等价命令 —— 想脱离界面复现问题很方便；
* 表单里有任何不合法的地方，底部会红字提示，并禁用「开始下载」；
* `Ctrl + Enter` 直接开始下载；
* 所有配置保存在浏览器本地（localStorage），下次打开还在。

---

## 命令行参数 → 界面位置对照表

| 命令行参数 | 界面位置 | 说明 |
| --- | --- | --- |
| `URL ...` | 「链接」→ 链接输入框 | 每行一个链接，支持 `kemono.cr` / `coomer.st` / `pawchive.pw`，作者页与单帖页都行 |
| `--batch-file FILE` | 「链接」→ 批次文件 | 可多选、可拖放；每行一个链接，界面会以 `--batch-file` 逐个传入 |
| `--favorite-creators-kemono` | 「链接」→ 收藏创作者开关 | Kemono 收藏 |
| `--favorite-creators-coomer` | 同上 | Coomer 收藏 |
| `--favorite-creators-pawchive` | 同上 | Pawchive 收藏 |
| `--path PATH` | 「保存位置」→ 保存目录 | 默认 `~/Downloads/kemono-dl`，可用内置目录选择器浏览磁盘 |
| `--output TEMPLATE` | 「命名模板」→ 自定义模板 | 单个模板时只传一条 `--output` |
| `--output attachments:T` 等 | 「命名模板」→ 分段模板 | 打开后分别填写附件 / 正文 / JSON 三套模板，等价于传三条带类型前缀的 `--output` |
| `--restrict-names` | 「保存位置」→ 仅 ASCII 文件名 | 把中文等字符替换掉，避免跨平台乱码 |
| `--no-tmp` | 「保存位置」→ 不使用 .tmp | 关闭「先写临时文件再改名」的保护 |
| `--custom-template-variables FILE` | 「命名模板」→ 自定义变量 | 直接粘贴 JSON，界面写入本地文件后传 `--custom-template-variables` |
| `--date [Type:]DATE` | 「过滤」→ 指定日期 | 每一行都是「开关 + 类型 + 日期」 |
| `--datebefore [Type:]DATE` | 「过滤」→ 该日期之前 | 同上 |
| `--dateafter [Type:]DATE` | 「过滤」→ 该日期之后 | 同上 |
| 日期类型 `added:` / `edited:` / `published:` | 每行的类型下拉框 | 默认 `published`，界面会拼成 `published:20240506` 这样的形式 |
| `--skip-extensions EXTs` | 「过滤」→ 跳过扩展名 | 输入框回车/逗号添加成标签，最终拼成逗号分隔列表 |
| `--skip-attachments` | 「过滤」→ 跳过附件 | 只写正文 / JSON 时用 |
| `--write-content` | 「保存位置」→ 保存正文 | 把帖子正文写成 HTML |
| `--write-json` | 「保存位置」→ 保存 JSON | 把帖子 API 响应写成 JSON |
| `--archive FILE` | 「过滤」→ 归档文件 | 增量下载：记录已下载帖子，下次自动跳过 |
| `--cookies FILE` | 「账号」→ cookies 文件 | 可多选，逐个传 `--cookies` |
| `--kemono-login USER PASS` | 「账号」→ Kemono 登录 | 用户名 + 密码 |
| `--coomer-login USER PASS` | 「账号」→ Coomer 登录 | 用户名 + 密码 |
| `--pawchive-login USER PASS` | 「账号」→ Pawchive 登录 | 用户名 + 密码 |
| `--version` | 顶部版本徽章 / 「关于」面板 | 显示当前 `kemono-dl` 版本 |

> 收藏下载通常需要 cookies 或登录态；两者都没有时界面会给出黄色提醒，
> 但仍允许你执行（只是服务端大概率要求登录）。

---

## 输出模板

模板与命令行完全一致，`{变量}` 会按帖子信息替换，`/` 分隔子目录。

默认模板：

```
{service}/{creator_id}/{post_id}/{filename}
```

内置预设（下拉框切换）：

| 预设 | 模板 |
| --- | --- |
| 默认（service/creator/post） | `{service}/{creator_id}/{post_id}/{filename}` |
| 按作者名分组 | `{service}/{creator_name} [{creator_id}]/{filename}` |
| 按发布日期分组 | `{service}/{creator_id}/{published:%Y%m%d}/{filename}` |
| 旧版兼容 | `{service}/{creator_name} [{creator_id}]/[{published:%Y%m%d}] [{post_id}] {post_title}/{index}_{filename}` |

界面下方会给出**实时路径预览**（用示例数据渲染），改模板就能立刻看到
最终文件会落在哪里，同时校验非法字符与空模板。

可用变量：`service`、`creator_id`、`creator_name`、`post_id`、`post_title`、
`attachments_count`、`added`、`published`、`edited`、`server_filename`、
`server_file_name`、`server_file_ext`、`filename`、`file_name`、`file_ext`、
`sha256`、`index`，以及在 JSON 里自定义的变量。

---

## 任务、进度与日志

* 任务**串行执行**（下一个任务等上一个结束），避免抢占同一个 cookies / 归档文件；
* 进度条、已下载大小、速度、ETA、帖子数、文件数都是从 CLI 真实输出里解析出来的
  （`[downloading] 12.34% of 5.6 MB eta 0:00:12 at 480.2 KB/s`）；
* 日志面板保留完整输出，可一键保存为 `.txt`；
* 「停止」会结束整个进程树（Windows 下用 `taskkill /T`）；
* 失败的任务可以「重试」，会以同样的参数重新入队；
* 任务完成后可直接「打开目标文件夹」。

> 界面不会自己实现下载逻辑，也不会改写 CLI 的输出，因此日志就是原版
> `kemono-dl` 的日志，排查问题时可以直接对照。

---

## 构建便携版 exe

构建只需要本机有 Python 3.11+；**成品**在别人机器上不需要 Python。

```bash
python tools/build_exe.py
```

脚本会：

1. 从 PyPI 直接下载 `requests` 与 PyInstaller 的 wheel（不依赖 pip），解包到 `.build/site`；
2. 调用 PyInstaller，按 `kemono-dl-gui.spec` 打包 `gui_main.py`，把
   `kemono_dl_gui/static` 作为数据文件塞进去；
3. 产出 `dist/kemono-dl-gui.exe`（单文件，约 12 MB）。

参数：`--skip-deps` 复用已下载的依赖；`--keep-work` 保留 PyInstaller 中间目录。
Windows 用户也可以双击 `构建便携版.bat`。

### 云端构建（GitHub Actions，推荐交付方式）

本地打不开 exe 也没关系：仓库自带 `.github/workflows/build-gui.yml`，
在 **真实 Windows 运行器**上完成「测试 → 打包 → 真的启动 exe 验证」全流程。

* 手动触发：仓库 → Actions → **Build GUI (portable exe)** → Run workflow；
* 向 `main` 推送改动、或发布 Release 时也会自动跑；
* 构建产物在该次运行的 **Artifacts → kemono-dl-gui-windows-x64** 里下载；
* 如果是发布 Release，exe 会自动附加到 Release 资产上。

CI 里跑的不只是「打包成功」，还包括 `tools/verify_exe.py`：它会像用户一样
直接启动 `dist/kemono-dl-gui.exe`，然后从外部检查 `/api/meta` 报告
`frozen=true`、`hasRequests=true`、预览命令里带 `--run-cli`、静态资源能取到，
最后调用 `/api/quit` 确认进程真的退出。

打包版启动时，下载任务会以 `kemono-dl-gui.exe --run-cli <参数>` 的形式
**再次调用自己**，因此在冻结环境里也走的是同一套 CLI 代码路径。

---

## 自检工具

| 脚本 | 作用 |
| --- | --- |
| `python tools/smoke_test.py` | 起服务、走一遍 `/api/meta` `/api/fs` `/api/preview` `/api/validate` `/api/state` `/api/quit`，输出 JSON |
| `python tools/job_test.py [URL]` | 真的跑一次下载任务，验证「表单 → 命令行 → 子进程 → 日志/进度 → 任务状态」整条链路 |
| `python tools/verify_exe.py` | 启动已打包的 `dist/kemono-dl-gui.exe`，检查冻结模式、内置依赖、静态资源与退出流程（CI 用）；设 `KEMONO_DL_GUI_EXE` 可指向别处的 exe 副本 |
| `python tools/check_exe_bundle.py` | 不启动 exe，直接解析 PyInstaller 归档：内置解释器、MSVC 运行库、SSL、CA 证书、前端资源、`--run-cli` 自调用路径是否都在包里 |
| `python tools/check_ui.py` | 检查 `app.js` 里用到的每个元素 id 是否都在 `index.html` 中存在 |
| `python -m unittest tests.test_gui_args` | 18 个单元测试，逐项核对界面控件与 CLI 参数的映射 |
| `python tools/fetch_wheels.py` | 手动下载 wheel（pip 不可用时的兜底） |

---

## 常见问题

**目标机器需要装 Python 吗？**
不需要。`kemono-dl-gui.exe` 是 PyInstaller 单文件打包，里面已经带了完整的
CPython 3.12 运行时、`requests`/`urllib3`/`certifi` 和 CA 证书。下载任务由
exe 以 `kemono-dl-gui.exe --run-cli …` 再次调用自己执行，所以整条链路都不碰
宿主机上的 Python。用 `python tools/check_exe_bundle.py` 可以从归档层面逐项验证。

**端口被占用？**
用 `python -m kemono_dl_gui --port 0`，会自动挑一个空闲端口；便携版重复双击会
分别占用不同端口，互不影响。便携版若默认端口被占用，也会自动退回随机端口启动。

**怎么彻底退出？**
点左侧栏底部「退出程序」。如果窗口已经关了但进程还在（任务管理器里能看到
`kemono-dl-gui.exe`），也可以直接在任务管理器结束它 —— 正在下载的任务同样会停止。

**为什么界面是浏览器？**
这样可以用纯 Python 标准库实现，不引入 Tkinter/Qt 之类的重依赖，同时拿到
现代的排版、动画和主题能力；服务只监听 `127.0.0.1`，并且每个会话都带一次性
token（`X-GUI-Token`），别的网页无法调用你的下载接口。

**下载很慢 / 失败？**
界面显示的报错就是 CLI 的报错。常见原因：需要 cookies 或登录、站点临时不可用、
文件服务器失效（见 README 顶部关于 kemono/coomer 文件服务器的说明）。

**配置存在哪？**
界面配置在浏览器 localStorage；上传的 cookies / 批次文件副本与自定义变量
放在 `%LOCALAPPDATA%\kemono-dl-gui\`（可用环境变量 `KEMONO_DL_GUI_DATA` 改）。
