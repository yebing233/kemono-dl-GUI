"""简单模式 / 专业模式 的静态检查。

前端没有浏览器可跑，这里退一步做静态断言：只要标记、样式规则或接线少了一处，
界面上就会出现「关了专业模式还显示高级选项」或者「一打开就闪一下完整界面」这类问题。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "kemono_dl_gui" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "styles.css").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")


def tag_ids(markup: str, attribute: str) -> list[str]:
    """Return the id of every element carrying the given data attribute."""
    found: list[str] = []
    for match in re.finditer(r"<[^>]*\b" + re.escape(attribute) + r"\b[^>]*>", markup):
        tag = match.group(0)
        identifier = re.search(r'id="([^"]+)"', tag)
        if identifier:
            found.append(identifier.group(1))
    return found


class ModeMarkupTests(unittest.TestCase):
    def test_body_defaults_to_simple_mode(self) -> None:
        """没有这个属性，首屏会先渲染完整界面再收起。"""
        self.assertIn('<body data-mode="simple">', HTML)

    def test_advanced_cards_are_marked(self) -> None:
        for card in ("sec-template", "sec-filters", "sec-account"):
            self.assertRegex(
                HTML,
                r'<section class="card" id="' + card + r'" data-adv>',
                f"{card} 应标记为 data-adv",
            )

    def test_simple_mode_has_its_own_naming_card(self) -> None:
        self.assertIn('id="sec-naming-simple" data-simple', HTML)
        # 作者文件夹三选一 + 日期 / 标题 / 编号 三个勾选框
        self.assertIn('id="authorFolderMode"', HTML)
        for chip in ("nameDate", "nameTitle", "namePostId"):
            self.assertIn(f'id="{chip}"', HTML)
        self.assertIn('class="check-chip"', HTML)

    def test_advanced_fields_hidden_but_still_collected(self) -> None:
        for control in ("swRestrict", "swNoTmp", "swWriteJson"):
            self.assertRegex(
                HTML,
                r'<label class="switch-row" data-adv>\s*<input[^>]*id="' + control + r'"',
                f"{control} 应放进带 data-adv 的开关行",
            )
        # 简单模式保留正文开关，否则用户会以为没有任何「顺带保存」能力
        self.assertNotRegex(
            HTML,
            r'<label class="switch-row" data-adv>\s*<input[^>]*id="swWriteContent"',
        )
        # 隐藏的输入仍然要参与 collect()，否则切回专业模式会丢配置
        for control in ("swRestrict", "swNoTmp", "swWriteJson"):
            self.assertIn(f"'{control}'", JS)


class ModeStyleTests(unittest.TestCase):
    def test_css_hides_both_directions(self) -> None:
        self.assertIn('body[data-mode="simple"] [data-adv]', CSS)
        self.assertIn('body[data-mode="pro"] [data-simple]', CSS)

    def test_simple_mode_hides_cli_flag_hints(self) -> None:
        self.assertIn('body[data-mode="simple"] .switch-text em:not(.keep-note)', CSS)

    def test_step_badge_and_settings_styles_exist(self) -> None:
        for selector in (".step-badge", ".pill-button", ".simple-preview", ".settings-actions"):
            self.assertIn(selector, CSS)


class ModeScriptTests(unittest.TestCase):
    def test_mode_state_is_persisted(self) -> None:
        self.assertIn("MODE_KEY = 'kemono-dl-gui.mode'", JS)
        self.assertIn("localStorage.setItem(MODE_KEY", JS)

    def test_mode_is_applied_before_first_paint(self) -> None:
        self.assertIn("applyMode(loadMode(), false)", JS)

    def test_settings_controls_are_wired(self) -> None:
        for control in ("openSettings", "modePill", "openSettingsLink", "swProMode", "authorFolderMode"):
            self.assertIn(f"$('{control}')", JS)
            self.assertIn(f'id="{control}"', HTML)

    def test_naming_controls_compose_the_template(self) -> None:
        """勾选项必须真的拼进模板，否则界面上勾了等于没勾。"""
        self.assertIn("function buildTemplate(", JS)
        self.assertIn("function deriveNaming(", JS)
        self.assertIn("function applyNaming(", JS)
        self.assertIn("'{creator_name} [{creator_id}]'", JS)
        self.assertIn("'{published:%Y.%m.%d}'", JS)
        self.assertIn("'{post_title}'", JS)
        self.assertIn("'[{post_id}]'", JS)
        for control in ("nameDate", "nameTitle", "namePostId"):
            self.assertIn(f"'{control}'", JS)

    def test_author_folder_defaults_to_name_and_id(self) -> None:
        self.assertIn("FALLBACK_TEMPLATE = '{service}/{creator_name} [{creator_id}]/{post_id}/{filename}'", JS)
        body = JS.split("function applyConfig(", 1)[1].split("\nfunction ", 1)[0]
        self.assertIn("syncNaming();", body)

    def test_settings_modal_is_closed_with_the_others(self) -> None:
        body = JS.split("function closeModals()", 1)[1].split("}", 1)[0]
        self.assertIn("settingsModal", body)


if __name__ == "__main__":
    unittest.main()
