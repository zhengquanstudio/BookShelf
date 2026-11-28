"""T16：运行 page_frame.js 的 Node 单测，验证「固定页框」纯逻辑。

Node 不可用时自动跳过，保证 pytest 在无 node 环境下仍为绿；
有 node 时退出码非 0 即失败（让 CI/提交门禁覆盖到 JS 逻辑）。
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

_NODE = shutil.which("node")


@pytest.mark.skipif(_NODE is None, reason="node 未安装，跳过 page_frame.js 单测")
def test_page_frame_node_suite() -> None:
    test_file = os.path.join(os.path.dirname(__file__), "test_page_frame.js")
    result = subprocess.run(
        [_NODE, test_file],  # noqa: S603  _NODE 来自 which，可信
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
