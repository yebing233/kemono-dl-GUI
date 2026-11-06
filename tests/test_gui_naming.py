"""用户自定义命名方案：专业模式保存 → 简单模式套用。

没有浏览器可跑，这里仍然做静态断言，但覆盖的是「数据从哪来、存到哪、怎么接上」
这些一断就失效的关键点：少一个 id 就点不动，少一次 render 就不出现在下拉框里。
"""

from __future__ import annotations

import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "kemono_dl_gui" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "styles.css").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")


class NamingMarkupTests(unittest.TestCase):
    def test_pro_mode_has_the_save_row(self) -> None:
        for control in ("namingName", "saveNaming", "savedNaming"):
            self.assertIn(f'id="{control}"', HTML, f"专业模式缺少 {control}")
        self.assertIn("添加到简单模式", HTML)

    def test_simple_mode_has_the_scheme_select(self) -> None:
        self.assertIn('id="customNaming"', HTML)
        body = HTML.split('id="sec-naming-simple"', 1)[1].split("</section>", 1)[0]
        self.assertIn('id="customNaming"', body, "方案下拉应放在简单模式的命名卡片里")


class NamingScriptTests(unittest.TestCase):
    def test_schemes_are_persisted_locally(self) -> None:
        self.assertIn("NAMING_KEY = 'kemono-dl-gui.naming.v1'", JS)
        self.assertIn("localStorage.setItem(NAMING_KEY", JS)
        self.assertIn("localStorage.getItem(NAMING_KEY", JS)

    def test_save_apply_remove_flow_exists(self) -> None:
        for name in ("loadNamingPresets", "storeNamingPresets", "renderNamingPresets",
                     "saveCurrentNaming", "applyCustomNaming", "removeNamingPreset"):
            self.assertIn(f"function {name}(", JS, f"缺少 {name}")

    def test_saving_reads_the_active_template(self) -> None:
        body = JS.split("function saveCurrentNaming()", 1)[1].split("\nfunction ", 1)[0]
        self.assertIn("activeTemplate()", body, "必须保存当前正在编辑的模板")
        self.assertIn("renderNamingPresets()", body)
        self.assertIn("storeNamingPresets(", body)

    def test_unknown_variables_are_rejected(self) -> None:
        body = JS.split("function saveCurrentNaming()", 1)[1].split("\nfunction ", 1)[0]
        self.assertIn("SAMPLE_VARS", body)
        self.assertIn("不认识的变量", body)

    def test_simple_mode_select_is_synced_both_ways(self) -> None:
        sync = JS.split("function syncNaming()", 1)[1].split("\nfunction ", 1)[0]
        self.assertIn("$('customNaming')", sync)
        self.assertIn("APP.naming.find(", sync)
        wiring = JS.split("schemeSelect.addEventListener", 1)[1][:400]
        self.assertIn("applyCustomNaming", wiring)

    def test_presets_dropdown_lists_saved_schemes(self) -> None:
        self.assertIn("我保存的方案", JS)
        self.assertIn("custom:${entry.id}", JS)

    def test_schemes_are_loaded_at_boot(self) -> None:
        self.assertIn("APP.naming = loadNamingPresets();", JS)
        self.assertIn("renderNamingPresets();", JS.split("function boot()", 1)[1])

    def test_cap_keeps_the_list_usable(self) -> None:
        self.assertIn(".slice(0, 20)", JS)
        self.assertIn("最多保存 20 个方案", JS)


class NamingStyleTests(unittest.TestCase):
    def test_scheme_widgets_are_styled(self) -> None:
        for selector in (".naming-save", ".naming-save-row", ".saved-naming",
                         ".saved-item", ".saved-remove", ".saved-empty"):
            self.assertIn(selector, CSS, f"缺少样式 {selector}")


if __name__ == "__main__":
    unittest.main()
