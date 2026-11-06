# kemono-dl GUI 使用说明

一个本地运行的现代化图形界面，覆盖 `kemono-dl` 命令行里的**全部**参数。
界面本身只做两件事：把你的选择翻译成真实的 `kemono-dl` 参数，然后把真实的
下载进程跑起来 —— 所以命令行有什么能力，界面就有同样的能力，输出、日志、行为
完全一致。

![界面结构](#界面结构) · [免安装使用](#方式一便携版推荐无需-python) · [源码运行](#方式二源码运行) · [Docker 部署](#方式四docker-部署服务器--nas--群晖) · [功能对照表](#命令行参数--界面位置对照表)

---

## 四种打开方式

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
| `--host` | 监听地址，默认 `127.0.0.1`（仅本机）；Docker / 远程部署用 `0.0.0.0` 并配合 `KEMONO_DL_GUI_PASSWORD` |
| `--port` | 监听端口，默认 `8765`，写 `0` 表示自动挑一个空闲端口 |
| `--no-browser` | 启动后不自动打开浏览器 |

对应环境变量：`KEMONO_DL_GUI_HOST`、`KEMONO_DL_GUI_PORT`、`KEMONO_DL_GUI_NO_BROWSER=1`、
`KEMONO_DL_GUI_PASSWORD`（HTTP Basic 访问密码）、`KEMONO_DL_GUI_DOWNLOAD_DIR`（默认保存位置）、
`KEMONO_DL_GUI_DATA`（数据目录）。

### 方式三：pip 安装后使用命令

```bash
pip install .
kemono-dl-gui        # 等同于 python -m kemono_dl_gui
```

### 方式四：Docker 部署（服务器 / NAS / 群晖）

镜像里已经装好 Python 和依赖，容器内以「无浏览器」模式跑网页界面，宿主机只要
浏览器就能用：

```bash
# 方式 A：docker compose（推荐）
docker compose -f docker-compose.gui.yml up -d --build
# 然后打开 http://127.0.0.1:8765/

# 方式 B：纯 docker
docker build -f Dockerfile.gui -t kemono-dl-gui .
docker run -d --name kemono-dl-gui \
  -p 127.0.0.1:8765:8765 \
  -v "$PWD/downloads:/downloads" \
  -v kemono-gui-data:/data \
  -e KEMONO_DL_GUI_PASSWORD=change-me \
  --restart unless-stopped \
  kemono-dl-gui
```

不想自己构建也可以直接用 GitHub Actions 产出的镜像（第一次用需要在仓库的
Packages 页面把包改成 public）：

```bash
docker pull ghcr.io/yebing233/kemono-dl-gui:latest
```

容器用到的环境变量：

| 变量 | 默认值（镜像内） | 说明 |
| --- | --- | --- |
| `KEMONO_DL_GUI_HOST` | `0.0.0.0` | 监听地址；容器内必须是 `0.0.0.0`，否则端口映射进不来 |
| `KEMONO_DL_GUI_PORT` | `8765` | 监听端口 |
| `KEMONO_DL_GUI_PASSWORD` | 空 | **强烈建议设置**。设置后整个界面走 HTTP Basic 认证（用户名随便填，密码填这个值）。想给局域网用就把端口映射改成 `"8765:8765"`，并且一定配上密码 |
| `KEMONO_DL_GUI_DOWNLOAD_DIR` | `/downloads` | 界面「保存位置」的默认值 |
| `KEMONO_DL_GUI_DATA` | `/data` | cookies / 批次文件 / 自定义模板变量的落盘位置 |
| `KEMONO_DL_GUI_NO_BROWSER` | `1` | 不尝试打开浏览器（容器里没有桌面） |

挂载点：`/downloads` 放下载结果，`/data` 放上传的 cookies、批次文件等；两个都建议
挂宿主机目录，容器重建不丢数据。

`GET /healthz` **不需要任何认证**，返回 `ok`，专门给 Docker healthcheck / 反向代理
探活用。其余所有路径在没有密码时对「能连上端口的人」开放，所以：

* 只在宿主机用 → 保持 `127.0.0.1:8765:8765`；
* 要外网/局域网访问 → 必须设置 `KEMONO_DL_GUI_PASSWORD`，最好再套一层 HTTPS
  （Nginx / Caddy 反代），因为 Basic 认证本身是明文传输的。

> 容器里没有桌面环境，界面的「打开文件夹」按钮会提示失败，属正常现象；从宿主机
> 的 `./downloads` 目录取文件即可。

---

## 简单模式与专业模式

界面默认是**简单模式**：一屏只留三件事——粘贴链接、选保存位置、开始下载。
所有参数名、`--xxx` 提示、模板变量、cookies / 登录 / 日期过滤都收进 **设置 → 专业模式**。

打开方式二选一：

* 点右上角的模式徽标（显示「简单模式」的那个小胶囊）；
* 或点左侧栏底部的 **设置**，在面板里打开 **专业模式** 开关。

> 切换只影响「显示」：专业模式里填过的模板、过滤、登录信息会原样保留并继续生效，
> 切回简单模式只是把它们藏起来。模式选择存在浏览器 localStorage 里，下次打开还保持。

| 模式 | 显示的内容 | 适合谁 |
| --- | --- | --- |
| 简单模式（默认） | 链接 / 保存位置 / 命名方式（一个「用帖子标题命名」开关）/ 任务与日志 | 只想把图存下来的人 |
| 专业模式 | 全部：命名模板与变量、分段模板、日期过滤、跳过扩展名、归档、cookies、三站登录、自定义变量、命令行预览 | 需要复现命令行行为、或做增量 / 精细命名的人 |

简单模式里的「用帖子标题命名文件夹」其实就是一条快捷方式：
打开它等于把模板改成 `{service}/{creator_id}/{post_title} [{post_id}]/{filename}`，
关掉则回到默认的 `{service}/{creator_id}/{post_id}/{filename}`。
卡片下方会实时显示这条模板渲染出来的样例路径。

---

## 界面结构

专业模式下的布局：

```
┌──────────┬─────────────────────────────────────┬──────────────────────┐
│ 左侧导航  │ 中间：参数表单                        │ 右侧：任务队列与日志    │
│ 链接      │  ① 要下载什么：链接 / 批次 / 收藏       │  任务列表（串行队列）  │
│ 保存位置  │  ② 保存到哪里：目录 / 内容开关          │  进度条 / 大小 / 待下载│
│ 命名模板  │  ③ 文件怎么命名：模板 / 预设 / 变量     │  实时日志（可保存）     │
│ 过滤      │  ④ 只下载一部分：日期 / 扩展名 / 归档    │  停止 / 重试 / 打开目录 │
│ 账号      │  ⑤ 需要登录的内容：cookies / 登录       │                        │
│ 任务日志  │                                       │                        │
└──────────┴─────────────────────────────────────┴──────────────────────┘
            底部固定操作栏：命令行预览 · 复制命令 · 开始下载
```

简单模式下左侧栏只剩「链接 / 保存位置 / 命名方式 / 任务与日志」，
表单是 ① 要下载什么（只留一个链接输入框）→ ② 保存到哪里 → ③ 文件怎么命名 三步；
批次文件、收藏下载、命令行预览也会隐藏 —— 一次要贴很多链接时，直接在输入框里多粘几行即可。

* 右上角可切换**深色 / 浅色**主题（设置面板里也有一个同样的按钮），选择会自动记住；
* 专业模式底部会实时显示即将执行的完整命令行（密码显示为 `******`），点「复制命令」
  就能拿到一条可以贴到终端里直接跑的等价命令 —— 想脱离界面复现问题很方便；
* 表单里有任何不合法的地方，底部会红字提示，并禁用「开始下载」；
* `Ctrl + Enter` 直接开始下载；
* 所有配置保存在浏览器本地（localStorage），下次打开还在。

---

## 命令行参数 → 界面位置对照表

> 下表的位置指的是**专业模式**。简单模式只保留其中最常用的几项，
> 找不到某个选项时，先去 设置 打开专业模式。

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
| 仅用帖子标题命名（不含编号） | `{service}/{creator_id}/{post_title}/{filename}` |
| 帖子标题 + 编号 | `{service}/{creator_id}/{post_title} [{post_id}]/{filename}` |
| 按作者名分组 | `{service}/{creator_name} [{creator_id}]/{filename}` |
| 按发布日期分组 | `{service}/{creator_id}/{published:%Y%m%d}/{filename}` |
| 旧版兼容 | `{service}/{creator_name} [{creator_id}]/[{published:%Y%m%d}] [{post_id}] {post_title}/{index}_{filename}` |

> 想要「用帖子标题当文件夹名」就选第二行那个预设，等价于把模板改成
> `{service}/{creator_id}/{post_title}/{filename}`；想同时保留编号就选第三行
> （`{post_title} [{post_id}]`，目录形如 `限定・ステッカー セット [72927321]`）。
> 标题里的 `<>:"/\|?*` 等非法字符会被自动替换成 `_`；个别帖子标题为空时
> 会退化成空目录名，此时用带编号的预设更稳妥。

界面下方会给出**实时路径预览**（用示例数据渲染），改模板就能立刻看到
最终文件会落在哪里，同时校验非法字符与空模板。

可用变量：`service`、`creator_id`、`creator_name`、`post_id`、`post_title`、
`attachments_count`、`added`、`published`、`edited`、`server_filename`、
`server_file_name`、`server_file_ext`、`filename`、`file_name`、`file_ext`、
`sha256`、`index`，以及在 JSON 里自定义的变量。

---

## 任务、进度与日志

* 任务**串行执行**（下一个任务等上一个结束），避免抢占同一个 cookies / 归档文件；
* 进度条、已下载大小、速度、ETA 都是从 CLI 真实输出里解析出来的
  （`[downloading] 12.34% of 5.60 MiB eta 00:00:12 at 480.20 KiB/s`）；
* 任务面板的五块统计：**帖子**（`[downloading] Post:` 的条数）、**已下载**（真正下载完的
  文件数）、**待下载**（帖子声明的附件数 `[downloading] Attachments: N` 减去已下载）、
  **剩余大小**、**耗时**；
* 「待下载」的个数是精确的（来自每个帖子的附件计数），「剩余大小」只有正在下载的那个
  文件是已知的，其余按**已完成文件的平均大小**估算，所以数字前面带 `≈`，鼠标悬停可以看到
  平均单个文件大小；
* 下载器每秒会刷新约 10 次进度行（`\r` 重绘），界面按 `\r` 拆行后**实时**更新进度条；
  日志面板只保留每 5% 一条，避免几十万行刷屏；
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

### 不装 git 也能推送（`tools/push_github.py`）

网页拖拽上传会**静默跳过点开头的目录**（`.github/`、`.gitignore`、`.dockerignore`），
所以 Actions 常常「没被触发」。机器上没装 git 时，用仓库自带的脚本直接调 GitHub API：

```powershell
# 1. 先看会改什么（只读，不需要 token）
python tools/push_github.py --dry-run

# 2. 真正推送：token 放环境变量，别写进命令行历史
$env:GITHUB_TOKEN = "ghp_xxx"
python tools/push_github.py -m "GUI 1.0.4: 简单模式 + 专业模式"

# 3. 用完清掉
Remove-Item Env:\GITHUB_TOKEN
```

token 在 <https://github.com/settings/tokens> 生成：细粒度 token 给目标仓库
`Contents: Read and write`，经典 token 勾 `repo`。脚本只依赖标准库，做的事和
`git add -A && git commit && git push` 一样：按 git 对象格式算 blob SHA、只上传变化的
文件、用 `base_tree` 生成新树、创建 commit、快进 `refs/heads/main`。
默认只增改不删除，要严格镜像远端就加 `--prune`。

有 git 的话，这条路更短：

```powershell
winget install --id Git.Git -e --source winget
git init -b main; git add -A; git commit -m "GUI 1.0.4"
git remote add origin https://github.com/yebing233/kemono-dl-GUI.git
git push -u origin main
```

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
| `python -m unittest tests.test_gui_streams` | 5 个单元测试，保证日志管道强制 UTF-8 且不做块缓冲（日文标题不崩、进度不延迟） |
| `python -m unittest tests.test_gui_server` | 18 个单元测试，覆盖 Docker 相关逻辑（密码校验、下载目录/数据目录环境变量）与进度行解析 |
| `python -m unittest tests.test_downloader_progress` | 2 个单元测试，确认 stdout 是管道时仍逐块输出 `\r` 进度（进度条不再停在 0%） |
| `python -m unittest tests.test_gui_modes` | 12 个静态断言，保证简单模式默认收起高级选项、专业模式开关与「用帖子标题命名」接线完整 |
| `python tools/docker_test.py` | 以 `0.0.0.0` + 密码模式启动，验证 `/healthz`、401/200、令牌与退出 |
| `python tools/push_github.py --dry-run` | 不装 git，直接对比本地目录与远端分支：列出将新增/修改/删除的文件，付 token 后一次性提交 |
| `python -m unittest tests.test_push_github` | 7 个单元测试，核对 git blob SHA 算法与上传忽略规则（点开头文件必须收、`dist`/`.build` 必须排除） |
| `python tools/fetch_wheels.py` | 手动下载 wheel（pip 不可用时的兜底） |

---

## 常见问题

**目标机器需要装 Python 吗？**
不需要。`kemono-dl-gui.exe` 是 PyInstaller 单文件打包，里面已经带了完整的
CPython 3.12 运行时、`requests`/`urllib3`/`certifi` 和 CA 证书。下载任务由
exe 以 `kemono-dl-gui.exe --run-cli …` 再次调用自己执行，所以整条链路都不碰
宿主机上的 Python。用 `python tools/check_exe_bundle.py` 可以从归档层面逐项验证。

**日志里出现日文/韩文标题会乱码或报错吗？**
不会。打包版是「无控制台」程序，PyInstaller 启动解释器时会忽略
`PYTHONUTF8`/`PYTHONIOENCODING`，CPython 于是按系统 ANSI 代码页（简体中文是
GBK）创建 `sys.stdout`，遇到 GBK 表示不了的字符（例如日文标题里的 `・` U+30FB）
就会抛 `UnicodeEncodeError: 'gbk' codec can't encode character`。GUI 的 CLI 子进程
启动时会把它重新配置为 UTF-8（`errors="replace"` 兜底），所以任何语言的标题都能
安全写进右侧日志面板。回归测试见 `tests/test_gui_streams.py`。

**「待下载」为什么不会一开始就显示全部数量？**
原版 CLI 是「读一个帖子 → 下载它的附件」，只有轮到某个帖子时才会打印
`[downloading] Attachments: N`，所以在它读到下一个帖子之前，界面并不知道后面还有多少文件。
界面按「已读到的帖子声明的附件总数 − 已下载」来算，随着帖子被读取逐步变大再收敛到 0。
想提前知道总量，只能靠站点 API 预扫描，那会额外发一堆请求，这里没有做。

**「剩余大小」前面为什么有 `≈`？**
附件列表里只有文件名和路径，没有文件体积，真实大小要等响应头返回。所以只有正在下载的那个
文件是精确值，其余按已完成文件的平均体积估算（鼠标悬停可以看到平均单文件大小）。数字会随着
下载推进越来越准。

**进度条一直停在 0%，日志半天才刷新？**
1.0.2 之前的版本会有这个现象：下载器只在 `sys.stdout.isatty()` 为真时才逐块重绘进度，
而界面里的子进程输出永远是管道，所以每个文件只在结束时打印一行；再加上打包版的
`sys.stdout` 是 8 KiB 块缓冲，日志要攒满一块才会冒出来。现在下载器无论是不是终端
都按 10 Hz 输出 `\r` 进度，打包版还会把 CLI 子进程的 stdout 换成直写管道的
`TextIOWrapper(write_through=True)`，进度条和日志都是实时的。
（回归测试：`tests/test_downloader_progress.py`、`tests/test_gui_streams.py`）

**想让文件夹用帖子标题，而不是帖子编号？**
简单模式下直接打开「文件怎么命名」里的 **用帖子标题命名文件夹** 开关即可，
目录会变成 `{post_title} [{post_id}]`，编号还在，方便回查。

专业模式下则是在「命名模板」里选预设：

```
{service}/{creator_id}/{post_title}/{filename}                        ← 只用标题（丢弃编号）
{service}/{creator_id}/{post_title} [{post_id}]/{filename}            ← 标题 + 编号
```

标题里的非法字符（`<>:"/\|?*`）会被替换成 `_`；极少数帖子标题为空时目录名会退化成空串，
这种情况用带编号的写法更稳妥。

**打开界面发现选项变少了 / 找不到模板、日期过滤、登录？**
默认是简单模式。点右上角的模式徽标，或左侧栏底部 **设置**，把 **专业模式** 打开即可。
切回简单模式不会清掉这些设置，只是暂时不显示。

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
