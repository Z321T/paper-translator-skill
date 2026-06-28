# paper-translator--v1.1.0
##### 英文论文翻译skill

##### pdf原文转md格式译文

---

## Skill 结构

**路径：** `.claude/skills/paper-translator/`

### 文件组成

| 文件                                | 行数  | 用途                                 |
| ----------------------------------- | ----- | ------------------------------------ |
| `SKILL.md`                          | 175行 | 核心工作流                           |
| `references/translation-format.md`  | 151行 | 输出格式规范 + 注解示例              |
| `references/cs-glossary.md`         | 163行 | CS/ML 术语标准中英对照表（120+术语） |
| `scripts/pdf_extract_text.py`       | 46行  | 基础 pdfplumber 文本提取             |
| `scripts/pdf_extract_two_column.py` | 157行 | 双栏学术论文布局感知提取             |
| `scripts/pdf_check_structure.py`    | 82行  | 快速检测页数/元数据/章节头           |

### 核心设计（按三个确认答复）

| 要求                      | Skill 的处理方式                                             |
| ------------------------- | ------------------------------------------------------------ |
| 1. 全学科 + CS优化        | SKILL.md 覆盖全学科；`cs-glossary.md` 提供 CS/ML 术语标准翻译（持续学习、层次分类、方法/架构、评估等 120+ 术语） |
| 2. 脚本作为参考代码       | 与 pdf skill 同模式：SKILL.md 中描述何时 fallback 到脚本，脚本独立可运行，需 `uv pip install pdfplumber` |
| 3. 方案B：AI直读PDF防丢失 | 主工作流用 **Read 工具**逐页读取（3-5页/次），跳过页眉页脚/页码，保留所有正文+图表 caption+公式。仅当 Read 失败时才用 Python 脚本做文本提取 |

### 工作流（5步）

1. **Assess**：Read 工具先读前3页判断单/双栏、章节结构
2. **Extract**：逐页读取，捕获标题/正文/公式/caption/脚注（跳过页眉页脚/页码/DOI）
3. **Translate**：逐段双语输出，EN段落→CN段落，公式/citation原样保留
4. **Assemble**：写入 `paper_translation.md`，含完整元数据头和附录
5. **Verify**：检查清单确保无遗漏

---

