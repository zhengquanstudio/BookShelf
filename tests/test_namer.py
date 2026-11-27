"""文档第 7.4 节 20 条命名测试用例（全部使用文档示例规则）。"""

from __future__ import annotations

from pathlib import Path

from app.config import load_config, save_config
from app.core.authors import normalize_author
from app.core.naming import NamingRules, plan_target
from app.core.series import extract_volume, volume_text

RULES = NamingRules(
    author_dir_template="{作者}【{国家}】",
    file_template="{作者}-{书名} {卷号}.{扩展名}",
    chinese_author_no_country=True,
    country_style="long",
    hierarchy="series_first",
    series_subdir=False,
)


def _book(title: str, author: str, **extra) -> dict:
    book = {
        "title": title,
        "author_raw": author,
        "format": extra.pop("format", "epub"),
        "status": extra.pop("status", "ok"),
    }
    book.update(extra)
    return book


def _path(*parts: str) -> Path:
    return Path(*parts)


def test_case_01_basic() -> None:
    plan = plan_target(_book("了不起的盖茨比", "F.S. Fitzgerald"), RULES)
    assert plan.target_path == _path("菲茨杰拉德【美国】", "菲茨杰拉德-了不起的盖茨比.epub")


def test_case_02_volume_in_title() -> None:
    plan = plan_target(_book("三体", "刘慈欣", volume=1), RULES)
    assert plan.target_path == _path("刘慈欣", "刘慈欣-三体 第1卷.epub")


def test_case_03_series_volume() -> None:
    plan = plan_target(_book("三体", "刘慈欣", series_name="三体三部曲", volume=1), RULES)
    assert plan.target_path == _path("三体三部曲", "刘慈欣", "刘慈欣-三体 第1卷.epub")


def test_case_04_title_with_volume_words() -> None:
    plan = plan_target(_book("三体", "刘慈欣", volume=3), RULES)
    assert plan.target_name == "刘慈欣-三体 第3卷.epub"


def test_case_05_japanese_author() -> None:
    plan = plan_target(_book("挪威的森林", "村上春树", format="mobi"), RULES)
    assert plan.target_path == _path("村上春树【日本】", "村上春树-挪威的森林.mobi")


def test_case_06_harari_volume() -> None:
    plan = plan_target(_book("人类简史", "尤瓦尔·赫拉利", volume=1), RULES)
    assert plan.target_path == _path("尤瓦尔·赫拉利【以色列】", "尤瓦尔·赫拉利-人类简史 第1卷.epub")


def test_case_07_rowling_pdf() -> None:
    plan = plan_target(_book("哈利·波特", "J.K. Rowling", volume=1, format="pdf"), RULES)
    assert plan.target_path == _path("J.K.罗琳【英国】", "J.K.罗琳-哈利·波特 第1卷.pdf")


def test_case_08_chinese_author_no_country() -> None:
    plan = plan_target(_book("围城", "钱钟书", format="mobi"), RULES)
    assert plan.target_path == _path("钱钟书", "钱钟书-围城.mobi")


def test_case_09_marguez_volume() -> None:
    plan = plan_target(_book("百年孤独", "加西亚·马尔克斯", volume=1), RULES)
    assert plan.target_path == _path(
        "加西亚·马尔克斯【哥伦比亚】", "加西亚·马尔克斯-百年孤独 第1卷.epub"
    )


def test_case_10_noise_removed() -> None:
    plan = plan_target(
        _book("[z-lib.org] The Great Gatsby (高清).azw3", "F.S. Fitzgerald", format="azw3"),
        RULES,
    )
    assert plan.target_path == _path("菲茨杰拉德【美国】", "菲茨杰拉德-The Great Gatsby.azw3")


def test_case_11_duplicate_skipped() -> None:
    plan = plan_target(
        _book("了不起的盖茨比", "F.S. Fitzgerald", status="skipped", dup_group_id=7),
        RULES,
    )
    assert plan.status == "skip"
    assert plan.target_name == ""


def test_case_12_no_metadata_failed() -> None:
    plan = plan_target(
        _book("", "", format="epub", status="failed"),
        RULES,
    )
    assert plan.status == "failed"
    assert plan.target_name == ""


def test_case_13_drm() -> None:
    plan = plan_target(
        _book("某书", "某作者", status="drm", format="epub"),
        RULES,
    )
    assert plan.status == "drm"
    assert plan.target_name == ""


def test_case_14_illegal_chars() -> None:
    plan = plan_target(_book("活着/许三观: 卖血记", "余华"), RULES)
    assert "/" not in plan.target_name
    assert ":" not in plan.target_name
    assert "_" in plan.target_name


def test_case_15_long_title_truncated() -> None:
    plan = plan_target(_book("长" * 200, "刘慈欣"), RULES)
    assert len(plan.target_name) <= 130
    assert len(str(plan.target_path)) <= RULES.max_path_len


def test_case_16_author_last_first() -> None:
    info = normalize_author("Fitzgerald, F.S.")
    assert info.name_zh == "菲茨杰拉德"
    plan = plan_target(_book("The Great Gatsby", "Fitzgerald, F.S."), RULES)
    assert plan.target_path == _path("菲茨杰拉德【美国】", "菲茨杰拉德-The Great Gatsby.epub")


def test_case_17_target_exists_suffix() -> None:
    first = plan_target(_book("了不起的盖茨比", "F.S. Fitzgerald"), RULES)
    second = plan_target(
        _book("了不起的盖茨比", "F.S. Fitzgerald"), RULES, existing=[first.target_path]
    )
    assert second.target_name == "菲茨杰拉德-了不起的盖茨比 (2).epub"
    assert second.status == "conflict"


def test_unknown_foreign_author_has_no_empty_brackets() -> None:
    plan = plan_target(_book("机械宇宙", "Edward Dolnick"), RULES)
    assert "[]" not in str(plan.target_path)
    assert "【】" not in str(plan.target_path)
    assert "  " not in plan.target_name
    assert plan.status == "conflict"


def test_case_18_case_different_books() -> None:
    left = plan_target(_book("The Great Gatsby", "F.S. Fitzgerald"), RULES)
    right = plan_target(_book("the great gatsby", "F.S. Fitzgerald"), RULES)
    assert str(left.target_name) != str(right.target_name)
    assert str(left.target_path) != str(right.target_path)


def test_case_19_author_alias() -> None:
    info = normalize_author("周树人")
    assert info.name_zh == "鲁迅"
    plan = plan_target(_book("呐喊", "周树人"), RULES)
    assert plan.target_path == _path("鲁迅", "鲁迅-呐喊.epub")


def test_case_20_roman_volume() -> None:
    match = extract_volume("Vol. IV")
    assert match is not None and match.volume == 4
    assert volume_text(4) == "第4卷"
    plan = plan_target(_book("Some Book", "F.S. Fitzgerald", volume=4), RULES)
    assert plan.target_name == "菲茨杰拉德-Some Book 第4卷.epub"


def test_default_hierarchy_is_author_first() -> None:
    rules = NamingRules(file_template="{书名}.{扩展名}")
    plan = plan_target(_book("三体", "刘慈欣", series_name="地球往事", volume=1), rules)
    assert plan.target_path == _path("刘慈欣", "地球往事", "三体.epub")


def test_existing_settings_not_overwritten(tmp_path) -> None:
    path = tmp_path / "config.json"
    save_config(
        {"naming": {"hierarchy": "series_first", "file_template": "{作者}-{书名}.{扩展名}"}},
        path,
    )
    loaded = load_config(path)
    assert loaded["naming"]["hierarchy"] == "series_first"
    assert loaded["naming"]["file_template"] == "{作者}-{书名}.{扩展名}"


def test_volume_in_default_template() -> None:
    plan = plan_target(_book("三个火枪手", "刘慈欣", volume=1), NamingRules())
    assert plan.target_name == "刘慈欣 - 三个火枪手第1卷.epub"


def test_empty_volume_no_dangling_separator() -> None:
    plan = plan_target(_book("三个火枪手", "刘慈欣"), NamingRules())
    assert plan.target_name == "刘慈欣 - 三个火枪手.epub"
    assert "  " not in plan.target_name


def test_chinese_author_country_metadata_does_not_force_country() -> None:
    plan = plan_target(
        _book("样例", "中文作者", country_code="FR", country="法国", is_chinese=True),
        NamingRules(),
    )
    assert plan.target_dir == _path("中文作者")
