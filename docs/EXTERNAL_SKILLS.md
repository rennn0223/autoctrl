# 外部 Skill 擴充

AutoCtrl 可從獨立 Python 套件載入 Skill。外掛介面的用途是把 LLM 的結構化參數
轉成既有 `CommandRequest`；正常的 ROS 2 topic 發布與動作執行仍由 AutoCtrl 控制器處理。

## 信任與啟用規則

- 安裝套件不等於啟用，預設不會載入任何外掛。
- 只有列在 `AUTOCTRL_EXTERNAL_SKILLS` 的 entry-point provider 才會 import。
- 外掛與 AutoCtrl 在同一 Python 程序執行；允許 provider 等同授予完整的程序內 Python 程式碼執行權限。
- Allowlist 是明確授權機制，不是安全沙箱；不要安裝或允許來源不明的套件。
- 外掛 Skill 名稱不能覆蓋內建 Skill。
- 若同時設定 `AUTOCTRL_LLM_SKILLS`，外掛的 Skill 名稱也必須在該清單內。

## 套件介面

外掛套件的 `pyproject.toml` 宣告 `autoctrl.skills` entry-point group：

```toml
[project.entry-points."autoctrl.skills"]
my_robot = "my_autoctrl_skills:provide_skills"
```

Provider 回傳一組 `SkillDefinition`。Resolver 應為純轉換函式，不可直接建立 ROS node
或發布 topic；這是 provider 契約，並非程序隔離的技術保證。以下示例新增「低速前進」語意：

```python
from autoctrl.domain import LinearDirection, MotionIntent, MotionKind
from autoctrl.skills import SkillDefinition, SkillRisk, SkillSpec


def provide_skills():
    return (
        SkillDefinition(
            spec=SkillSpec(
                name="move_slowly",
                description="讓小車以低速向前移動；未指定秒數時持續移動。",
                risk=SkillRisk.MOTION,
                input_schema={
                    "type": "object",
                    "properties": {
                        "duration_s": {"type": "number", "exclusiveMinimum": 0}
                    },
                    "additionalProperties": False,
                },
            ),
            resolve=lambda args, text: MotionIntent(
                kind=MotionKind.MOVE_LINEAR,
                linear_direction=LinearDirection.FORWARD,
                duration_s=args.get("duration_s"),
                speed_mps=0.1,
                source="external_skill",
                original_text=text,
            ),
        ),
    )
```

在 AutoCtrl 的 uv 環境安裝可信任套件後，以 provider 名稱明確啟用：

```bash
uv pip install /path/to/my-autoctrl-skills
AUTOCTRL_EXTERNAL_SKILLS=my_robot autoctrl
```

進入 CLI 後輸入 `/skills`，可確認目前實際提供給 LLM 的能力與風險分類。

## 執行與參數驗證

啟動的 `uv sync --inexact` 保留以 `uv pip install` 安裝的可信外掛。
Skill 參數由 JSON Schema Draft 2020-12 驗證，包含 minimum/maximum、巢狀 object
及 array items 等限制；schema 必須內嵌，不支援 `$ref`，驗證不會存取網路。
外掛一般執行例外會轉成可恢復錯誤，CLI 回報後仍能處理下一個命令。
