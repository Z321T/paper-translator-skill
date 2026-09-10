# paper-translator--v1.2.0
##### 英文论文翻译skill

##### pdf原文转md格式译文

---

## Skill 结构

**路径：** `./skills/paper-translator/`

### 文件组成

| 文件                                | 行数  | 用途                                 |
| ----------------------------------- | ----- | ------------------------------------ |
| `SKILL.md`                          | 255行 | 核心工作流                           |
| `references/translation-format.md`  | 158行 | 输出格式规范 + 注解示例              |
| `references/cs-glossary.md`         | 163行 | CS/ML 术语标准中英对照表（120+术语） |
| `scripts/pdf_extract_text.py`       | 46行  | 基础 pdfplumber 文本提取             |
| `scripts/pdf_extract_two_column.py` | 157行 | 双栏学术论文布局感知提取             |
| `scripts/pdf_check_structure.py`    | 82行  | 快速检测页数/元数据/章节头           |
| `scripts/pdf_extract_images.py`     | 284行 | 跨平台提取位图、裁剪矢量/组合图并生成相对路径清单 |

### 核心设计（按三个确认答复）

| 要求                      | Skill 的处理方式                                             |
| ------------------------- | ------------------------------------------------------------ |
| 1. 全学科 + CS优化        | SKILL.md 覆盖全学科；`cs-glossary.md` 提供 CS/ML 术语标准翻译（持续学习、层次分类、方法/架构、评估等 120+ 术语） |
| 2. 跨平台参考脚本         | Python + PyMuPDF/pdfplumber，通过 `uv` 管理；不依赖 Windows、Linux 或 macOS 专属命令 |
| 3. 方案B：AI直读PDF防丢失 | 主工作流逐页读取并核对图像清单，保留正文、公式、图表题注和有意义的原图；文本提取失败时使用 Python 脚本 |
| 4. 可迁移图片资源         | Markdown 与 `<markdown-stem>_assets/` 组成一个输出包，图片一律使用相对 POSIX 路径引用 |
| 5. 跨账户权限继承         | 资源目录使用普通目录创建语义并继承输出位置权限，避免 Windows 桌面应用首次访问时要求手动授权 |

### 工作流（5步）

1. **Assess**：Read 工具先读前3页判断单/双栏、章节结构
2. **Extract**：逐页读取文本并提取图片；矢量/组合图按页面区域渲染为 PNG
3. **Translate**：逐段双语输出，EN段落→CN段落，公式/citation原样保留
4. **Assemble**：写入 `paper_translation.md` 和相邻的 `paper_translation_assets/`，图片使用相对路径
5. **Verify**：检查图片链接可解析，并验证整个输出包移动后仍然有效

---
