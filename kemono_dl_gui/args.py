"""Translation layer between the GUI configuration and the kemono-dl CLI.

Everything in this module is pure logic (no HTTP, no subprocess), so the same
rules power the live command preview, the validation endpoint and the real run.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_TEMPLATE = "{service}/{creator_id}/{post_id}/{filename}"
TEMPLATE_TYPES = ("attachments", "content", "json")
DATE_FILTERS = ("date", "datebefore", "dateafter")
DATE_TYPES = ("published", "added", "edited")
LOGIN_SITES = ("kemono", "coomer", "pawchive")
FAVORITE_SITES = ("kemono", "coomer", "pawchive")

URL_PATTERN = re.compile(
    r"^https://(kemono|coomer|pawchive)\.\w+/([^/]+)/user/([^/]+)(?:/post/([^/]+))?/?$",
    re.IGNORECASE,
)

#: Variables available inside an output template, mirroring
#: ``kemono_dl.models.FileTemplateVaribales`` with plausible sample values.
SAMPLE_VARIABLES: dict[str, Any] = {
    "service": "patreon",
    "creator_id": "12345",
    "creator_name": "Sample Creator",
    "post_id": "67890",
    "post_title": "Sample Post Title",
    "attachments_count": 3,
    "added": datetime(2025, 8, 13, 12, 0, 0),
    "published": datetime(2025, 8, 13, 12, 0, 0),
    "edited": datetime(2025, 8, 14, 9, 30, 0),
    "server_filename": "wm54swsglbfs4583qzp7u880tmglvdqzeg6vqni12s6ywfsk3l8afp5ycfwo2hw4.png",
    "server_file_name": "wm54swsglbfs4583qzp7u880tmglvdqzeg6vqni12s6ywfsk3l8afp5ycfwo2hw4",
    "server_file_ext": "png",
    "filename": "attachment.png",
    "file_name": "attachment",
    "file_ext": "png",
    "sha256": "wm54swsglbfs4583qzp7u880tmglvdqzeg6vqni12s6ywfsk3l8afp5ycfwo2hw4",
    "index": 1,
}

INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1F]')


class TemplateError(ValueError):
    """Raised when a template cannot be rendered."""


def sanitize_segment(value: str, replacement: str = "_") -> str:
    """Same sanitising rule the downloader applies to every path segment."""
    return INVALID_PATH_CHARS.sub(replacement, value).rstrip(" .")


def render_template(
    template: str,
    base_path: str = ".",
    restrict_names: bool = False,
    custom_variables: dict[str, str] | None = None,
    overrides: dict[str, Any] | None = None,
) -> str:
    """Render ``template`` the way ``kemono_dl.utils.generate_file_path`` does."""
    variables: dict[str, Any] = dict(SAMPLE_VARIABLES)
    variables.update(overrides or {})

    for key, expression in (custom_variables or {}).items():
        if not isinstance(expression, str):
            raise TemplateError(f"自定义变量 {key!r} 的值必须是字符串表达式")
        try:
            variables[key] = eval(expression.format(**variables))  # noqa: S307 - parity with the CLI
        except KeyError as exc:
            raise TemplateError(f"自定义变量 {key!r} 引用了未知变量 {{{exc.args[0]}}}") from exc
        except Exception as exc:  # noqa: BLE001 - surface every expression error
            raise TemplateError(f"自定义变量 {key!r} 表达式错误: {exc}") from exc

    segments: list[str] = []
    for segment in re.split(r"[\\/]", template):
        try:
            formatted = segment.format_map(variables)
        except KeyError as exc:
            raise TemplateError(f"未知模板变量 {{{exc.args[0]}}}") from exc
        except (ValueError, IndexError, AttributeError) as exc:
            raise TemplateError(f"模板语法错误: {exc}") from exc
        segments.append(sanitize_segment(formatted))

    path = Path(*[segment for segment in segments if segment]) if any(segments) else Path(".")
    if not path.is_absolute():
        path = Path(base_path) / path
    if restrict_names:
        path = Path(re.sub(r"[^\x20-\x7E]", "_", str(path)))
    return str(path)


def template_errors(template: str, base_path: str, restrict_names: bool, custom_variables: dict[str, str] | None) -> str | None:
    try:
        render_template(template, base_path, restrict_names, custom_variables)
    except TemplateError as exc:
        return str(exc)
    return None


# --------------------------------------------------------------------------- #
# config parsing helpers
# --------------------------------------------------------------------------- #
def _bool(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.lower() in {"1", "true", "yes", "on"})


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


#: Longest request delay the GUI accepts (seconds); anything above is nonsense.
MAX_REQUEST_INTERVAL = 60.0


def _interval(value: Any) -> float:
    """Coerce the request delay into ``[0, MAX_REQUEST_INTERVAL]``.

    ``None``/garbage falls back to ``1.0`` — the polite value pawchive asks for.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return 1.0
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 1.0
    if seconds != seconds:  # NaN
        return 1.0
    return max(0.0, min(MAX_REQUEST_INTERVAL, seconds))


def normalise_config(config: dict[str, Any], default_path: str) -> dict[str, Any]:
    """Coerce an incoming JSON body into a predictable configuration object."""
    templates_in = config.get("templates") or {}
    templates = {}
    for key in TEMPLATE_TYPES:
        value = templates_in.get(key)
        templates[key] = _text(value) if isinstance(value, str) else DEFAULT_TEMPLATE
        if not templates[key]:
            templates[key] = DEFAULT_TEMPLATE

    dates = {}
    for key in DATE_FILTERS:
        raw = (config.get("dates") or {}).get(key) or {}
        date_type = raw.get("type") if raw.get("type") in DATE_TYPES else "published"
        dates[key] = {
            "enabled": _bool(raw.get("enabled")),
            "type": date_type,
            "value": _text(raw.get("value")),
        }

    logins = {}
    for site in LOGIN_SITES:
        raw = (config.get("logins") or {}).get(site) or {}
        logins[site] = {"user": _text(raw.get("user")), "password": raw.get("password") if isinstance(raw.get("password"), str) else ""}

    favorite = {site: _bool((config.get("favorite") or {}).get(site)) for site in FAVORITE_SITES}

    return {
        "urls": [line.strip() for line in (config.get("urls") or "").splitlines() if line.strip() and not line.strip().startswith("#")]
        if isinstance(config.get("urls"), str)
        else _list(config.get("urls")),
        "batch_files": _list(config.get("batchFiles")),
        "path": _text(config.get("path")) or default_path,
        "templates": templates,
        "template_split": _bool(config.get("templateSplit")),
        "restrict_names": _bool(config.get("restrictNames")),
        "no_tmp": _bool(config.get("noTmp")),
        "write_content": _bool(config.get("writeContent")),
        "write_json": _bool(config.get("writeJson")),
        "custom_vars_text": _text(config.get("customVars")),
        "archive": _text(config.get("archive")),
        "dates": dates,
        "skip_extensions": [ext.strip().lstrip(".") for ext in _list(config.get("skipExtensions")) if ext.strip().lstrip(".")],
        "skip_attachments": _bool(config.get("skipAttachments")),
        "request_interval": _interval(config.get("requestInterval")),
        "cookies": _list(config.get("cookies")),
        "logins": logins,
        "favorite": favorite,
    }


def parse_custom_variables(text: str) -> tuple[dict[str, str], list[str]]:
    """Return (variables, errors) for the custom template variable JSON text."""
    if not text.strip():
        return {}, []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, [f"自定义变量不是合法 JSON：第 {exc.lineno} 行第 {exc.colno} 列，{exc.msg}"]
    if not isinstance(data, dict):
        return {}, ["自定义变量必须是 JSON 对象，例如 {\"indexPlusOne\": \"{index} + 1\"}"]
    errors = [f"自定义变量 {key!r} 的值必须是字符串表达式" for key, value in data.items() if not isinstance(value, str)]
    return {str(key): str(value) for key, value in data.items()}, errors


def date_argument(date_type: str, value: str) -> tuple[str | None, str | None]:
    """Convert an ``YYYY-MM-DD`` value into ``type:YYYYMMDD`` for the CLI."""
    if not value:
        return None, "日期不能为空"
    cleaned = value.strip()
    for pattern in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            parsed = datetime.strptime(cleaned, pattern)
            break
        except ValueError:
            continue
    else:
        return None, f"无法识别的日期 {value!r}，请使用 YYYY-MM-DD"
    return f"{date_type}:{parsed.strftime('%Y%m%d')}", None


# --------------------------------------------------------------------------- #
# command building
# --------------------------------------------------------------------------- #
class BuildResult:
    def __init__(self, argv: list[str], errors: list[str], warnings: list[str], title: str, config: dict[str, Any]):
        self.argv = argv
        self.errors = errors
        self.warnings = warnings
        self.title = title
        self.config = config

    def to_dict(self) -> dict[str, Any]:
        return {
            "argv": self.argv,
            "errors": self.errors,
            "warnings": self.warnings,
            "title": self.title,
            "config": self.config,
        }


def _display_argument(argument: str) -> str:
    """Quote an argv entry for the on-screen command preview."""
    if not argument or re.search(r'[\s"{}*?<>|&^]', argument):
        return '"' + argument.replace('"', '\\"') + '"'
    return argument


def shell_command(argv: list[str], python_exe: str | None = None) -> str:
    """Human readable command, with credentials masked."""
    parts: list[str] = []
    mask_remaining = 0
    for argument in argv:
        if mask_remaining:
            parts.append("******")
            mask_remaining -= 1
            continue
        parts.append(_display_argument(argument))
        if argument in {"--kemono-login", "--coomer-login", "--pawchive-login"}:
            mask_remaining = 2  # both USERNAME and PASSWORD
    return " ".join(parts)


def build_command(
    config: dict[str, Any],
    python_exe: str,
    default_path: str,
    custom_vars_file: str | None = None,
    frozen: bool = False,
) -> BuildResult:
    """Build the ``kemono_dl`` command line for the given GUI configuration.

    Two shapes are supported:

    * source checkout: ``python -u -m kemono_dl <args>``
    * frozen build:    ``kemono-dl-gui.exe --run-cli <args>`` — the packaged
      executable re-launches itself in command line mode, so the end user needs
      no Python installation at all.
    """
    cfg = normalise_config(config, default_path)
    errors: list[str] = []
    warnings: list[str] = []

    if frozen:
        argv: list[str] = [python_exe, "--run-cli"]
    else:
        argv = [python_exe, "-u", "-m", "kemono_dl"]

    custom_variables, variable_errors = parse_custom_variables(cfg["custom_vars_text"])
    errors.extend(variable_errors)

    # --- output ---------------------------------------------------------
    path = cfg["path"]
    if not path:
        errors.append("请选择保存目录")
    elif os.path.exists(path) and not os.path.isdir(path):
        errors.append(f"保存目录不是文件夹：{path}")
    argv += ["--path", path or default_path]

    if cfg["template_split"]:
        for template_type in TEMPLATE_TYPES:
            template = cfg["templates"][template_type]
            error = template_errors(template, path or default_path, cfg["restrict_names"], custom_variables)
            if error:
                errors.append(f"{template_type} 模板：{error}")
            argv += ["--output", f"{template_type}:{template}"]
    else:
        template = cfg["templates"]["attachments"]
        error = template_errors(template, path or default_path, cfg["restrict_names"], custom_variables)
        if error:
            errors.append(f"输出模板：{error}")
        argv += ["--output", template]

    if cfg["restrict_names"]:
        argv.append("--restrict-names")
    if cfg["no_tmp"]:
        argv.append("--no-tmp")

    if cfg["custom_vars_text"].strip():
        if custom_vars_file:
            argv += ["--custom-template-variables", custom_vars_file]

    # --- links ----------------------------------------------------------
    if not cfg["urls"] and not cfg["batch_files"] and not any(cfg["favorite"].values()):
        errors.append("请至少提供一个链接、一个批次文件，或勾选一个收藏下载选项")

    for url in cfg["urls"]:
        if not URL_PATTERN.match(url):
            warnings.append(f"链接格式可能不受支持：{url}")
    argv += cfg["urls"]

    for batch_file in cfg["batch_files"]:
        if not os.path.isfile(batch_file):
            errors.append(f"批次文件不存在：{batch_file}")
        argv += ["--batch-file", batch_file]

    for site in FAVORITE_SITES:
        if cfg["favorite"][site]:
            argv.append(f"--favorite-creators-{site}")
    if any(cfg["favorite"].values()) and not cfg["cookies"] and not any(item["user"] for item in cfg["logins"].values()):
        warnings.append("收藏下载通常需要先提供 cookies 文件或登录账号")

    # --- filters --------------------------------------------------------
    for key in DATE_FILTERS:
        item = cfg["dates"][key]
        if not item["enabled"]:
            continue
        value, error = date_argument(item["type"], item["value"])
        if error:
            errors.append(f"--{key}：{error}")
        elif value:
            argv += [f"--{key}", value]

    if cfg["skip_extensions"]:
        argv += ["--skip-extensions", ",".join(cfg["skip_extensions"])]
    if cfg["skip_attachments"]:
        argv.append("--skip-attachments")
    if cfg["write_content"]:
        argv.append("--write-content")
    if cfg["write_json"]:
        argv.append("--write-json")
    if abs(cfg["request_interval"] - 1.0) > 1e-9:
        argv += ["--request-interval", f"{cfg['request_interval']:g}"]
    if cfg["archive"]:
        if not os.path.isfile(cfg["archive"]):
            warnings.append(f"归档文件尚不存在，将自动创建：{cfg['archive']}")
        argv += ["--archive", cfg["archive"]]

    # --- account --------------------------------------------------------
    for cookie_file in cfg["cookies"]:
        if not os.path.isfile(cookie_file):
            errors.append(f"cookies 文件不存在：{cookie_file}")
        argv += ["--cookies", cookie_file]

    for site in LOGIN_SITES:
        login = cfg["logins"][site]
        if login["user"] and login["password"]:
            argv += [f"--{site}-login", login["user"], login["password"]]
        elif login["user"] or login["password"]:
            errors.append(f"{site} 登录需要同时填写用户名和密码")

    title = "下载任务"
    if cfg["urls"]:
        first = cfg["urls"][0]
        match = URL_PATTERN.match(first)
        title = f"{match.group(2)}/user/{match.group(3)}" if match else first
        if len(cfg["urls"]) > 1:
            title += f" 等 {len(cfg['urls'])} 个链接"
    elif cfg["batch_files"]:
        title = f"批次文件 · {os.path.basename(cfg['batch_files'][0])}"
    elif any(cfg["favorite"].values()):
        title = "收藏创作者 · " + ", ".join(site for site, enabled in cfg["favorite"].items() if enabled)

    return BuildResult(argv, errors, warnings, title, cfg)
