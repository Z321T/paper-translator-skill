# Translation Output Format Specification

## General Rules

- Output language: bilingual — English original then Chinese translation
- Section pattern: `## N. English Title | 中文标题`
- Paragraph pattern: English paragraph → blank line → Chinese paragraph → blank line
- All LaTeX formulas preserved verbatim in both English and Chinese sections
- Citations kept as `(Author et al., Year)` in both languages
- First mention of proper nouns: English (Chinese). Subsequent: English only.
- Meaningful PDF visuals appear at their logical positions as relative image links or faithful Markdown/Mermaid reconstructions.
- Image assets live beside the Markdown file in `<markdown-stem>_assets/`; links always use POSIX `/` separators.

## Complete Annotated Example

### Metadata Header

```markdown
# Online Continual Learning with Dynamic Label Hierarchies
## 在线持续学习中的动态标签层次结构（完整翻译版）

**作者**: Anonymous Authors | **单位**: Anonymous Institution | **发表**: ICML 2026
**注**: 本文为 ICML 2026 审稿中论文。
```

### Abstract

```markdown
## Abstract | 摘要

> English abstract text in blockquote...

> 中文摘要翻译在引用块中...
```

### Introduction Section

```markdown
## 1. Introduction | 引言

English paragraph text with inline formulas $f(x) = \sum_i w_i x_i$ and citations (Author et al., 2023).

中文翻译段落，保持公式原样 $f(x) = \sum_i w_i x_i$ 和引用标记 (Author et al., 2023)。

### 1.1 Subsection | 子章节标题

Subsection content follows the same pattern.
子章节内容遵循相同模式。
```

### Method Section (with formulas)

```markdown
## 4. Method: HALO | 方法：HALO

Our analysis reveals that the core challenge of DHOCL lies in the **misalignment** between evolving taxonomies and shifting feature spaces.

我们的分析揭示 DHOCL 的核心挑战在于演化分类体系与变化特征空间之间的**不对齐**。

$$\mathcal{L} = \mathcal{L}_{lin} + \mathcal{L}_{pro} + \mathcal{R} \quad \text{(9)}$$

### 4.1 Hierarchical Prototypes Regularization (HPR) | 层次原型正则化

**Goal:** Construct a flexible feature space that inherently reflects the hierarchical taxonomy.

**目标**：构建一个灵活的特征空间，使其内在地反映层次分类体系的结构。

Inspired by ProtoPNet (Chen et al., 2019), we introduce a lightweight adapter $f_A$...

受 ProtoPNet (Chen et al., 2019) 启发，我们引入一个轻量级适配器 $f_A$...
```

### Table Content

```markdown
**Table 1** (full results on CIFAR-100, FGVC-Aircraft, CUB-200, iNaturalist):

| Method | CIFAR-100 AAUC/FAUC/MS↓/FFAcc | Aircraft AAUC/FAUC/MS↓/FFAcc |
|:-------|:-----------------------------:|:----------------------------:|
| RS baseline | 54.0/37.6/1.22/25.3 | 20.2/16.2/2.03/9.9 |
| **Ours (HALO)** | **59.2/43.5/1.13/32.0** | **40.6/36.6/1.28/28.9** |

As shown in Table 1, HALO consistently improves all metrics.

如表 1 所示，HALO 持续提高所有指标。
```

### Figure/Table Captions

```markdown
![Figure 1: Comparison of three continual-learning settings](paper_translation_assets/page-003-figure-1.png)

**Figure 1:** Figure 1 illustrates the contrast between three settings: **(Top)** OCL uses flat labels only. **(Middle)** HLE and IIRC operate under strict coarse-to-fine curriculum. **(Bottom)** DHOCL allows arbitrary hierarchical levels at any time.

**图 1：** 图 1 展示了三种设定的对比：**（上）** OCL 仅使用平坦标签。**（中）** HLE 和 IIRC 在严格的粗到细课程下运行。**（下）** DHOCL 允许任意层次级别的标签在任何时间到达。
```

The image path is relative to `paper_translation.md`. Move the Markdown file and `paper_translation_assets/` together. For a custom file such as `survey.zh.md`, use `survey.zh_assets/`. If a custom stem contains spaces, parentheses, or non-ASCII characters, keep the extractor's percent-encoded Markdown destination so CommonMark parsers resolve it reliably.

### Appendix

```markdown
## Appendix A: Related Works | 附录A：相关工作

### Hierarchical Classification | 层次分类

Hierarchical classification addresses the problem of organizing and predicting multiple labels within taxonomic structures...

层次分类解决了在分类结构中组织和预测多个标签的问题...

Existing approaches can be mainly categorized into: **(1) Embedding-based methods**... **(2) Loss-based methods**... **(3) Architecture-based methods**...

现有方法主要可分为三类：**(1) 基于嵌入的方法**... **(2) 基于损失的方法**... **(3) 基于架构的方法**...
```

### Footer

```markdown
---

*This manuscript is under double-blind review by ICML 2026.*
*本手稿正在 ICML 2026 进行双盲审稿。*
```

## Content That Must Be Preserved Exactly

| Content | Rule |
|:--------|:-----|
| LaTeX inline `$...$` | Copy verbatim, never translate inside |
| LaTeX display `$$...$$` | Copy verbatim, keep blank lines around |
| Citations `(Author, Year)` | Copy verbatim |
| Footnote markers `[^1]` | Copy verbatim |
| Equation numbers `(1)`, `(3a)` | Copy verbatim |
| Algorithm line numbers | Copy verbatim |
| Dataset names (CIFAR-100, etc.) | English only |
| Model names (ResNet-50, ViT-B) | English (Chinese) on first use, English thereafter |
| Metric abbreviations (AAUC, MS) | English only, explain on first use |

## Content That Should Be Translated

| Content | Rule |
|:--------|:-----|
| All body text | Full translation |
| Section/subsection headers | Chinese after `\|` |
| Figure/table captions | Full translation, keep "Figure X:" prefix |
| Figure/image content | Insert a relative image link before the bilingual caption, or reconstruct faithfully in Markdown/Mermaid |
| Table column headers in annotations | Translate, add parenthetical English |
| Substantive footnotes | Full translation |
| Impact statements, ethics statements | Full translation |
| Copyright boilerplate | Summarize or translate concisely |

## Content To Skip

- Page numbers (e.g., "1", "2" at page top/bottom)
- Running headers ("Online Continual Learning with Dynamic Label Hierarchies" repeated)
- Conference/journal DOI/ISBN bars
- Reviewer instructions ("Confidential reviewer copy...")
- Empty decorative lines from PDF layout
