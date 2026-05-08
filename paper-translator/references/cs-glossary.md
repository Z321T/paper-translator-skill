# CS/ML Terminology Glossary

Standard Chinese translations for common computer science and machine learning terms. Use consistently throughout the translated document.

## Core ML Concepts

| English | Chinese | Notes |
|:--------|:--------|:------|
| machine learning | 机器学习 | |
| deep learning | 深度学习 | |
| neural network | 神经网络 | |
| training / train | 训练 | |
| inference | 推理 | |
| gradient descent | 梯度下降 | |
| backpropagation | 反向传播 | |
| stochastic gradient descent (SGD) | 随机梯度下降 | |
| loss function | 损失函数 | |
| objective function | 目标函数 | |
| regularization | 正则化 | |
| overfitting | 过拟合 | |
| underfitting | 欠拟合 | |
| generalization | 泛化 | |
| hyperparameter | 超参数 | |
| epoch | 训练轮次 / epoch | Can use English directly |
| batch / mini-batch | 批次 / 小批量 | |
| learning rate | 学习率 | |
| optimizer | 优化器 | |
| activation function | 激活函数 | |
| forward pass | 前向传播 | |
| backward pass | 反向传播 | |
| weight / parameter | 权重 / 参数 | |
| bias | 偏置 | |
| embedding | 嵌入 | Sometimes keep as "embedding" |
| latent space | 潜在空间 | |
| latent variable | 潜变量 | |
| representation | 表示 | Not "表征" for ML context |
| feature | 特征 | |
| feature extractor | 特征提取器 | |
| backbone | 骨干网络 | |
| encoder | 编码器 | |
| decoder | 解码器 | |
| transformer | Transformer | Usually keep English |

## Continual Learning

| English | Chinese | Notes |
|:--------|:--------|:------|
| continual learning (CL) | 持续学习 | Not "连续学习" |
| online continual learning (OCL) | 在线持续学习 | |
| lifelong learning | 终身学习 | |
| catastrophic forgetting | 灾难性遗忘 | |
| plasticity | 可塑性 | |
| stability | 稳定性 | |
| stability-plasticity trade-off / dilemma | 稳定性-可塑性权衡 | |
| experience replay | 经验回放 | |
| replay buffer / memory buffer | 回放缓冲区 | |
| reservoir sampling | 蓄水池采样 | |
| class-incremental learning | 类别增量学习 | |
| task-incremental learning | 任务增量学习 | |
| domain-incremental learning | 领域增量学习 | |
| task-free continual learning | 无任务边界的持续学习 | |
| knowledge distillation | 知识蒸馏 | |
| knowledge retention | 知识保持 | |
| knowledge consolidation | 知识巩固 | |
| non-stationary data stream | 非平稳数据流 | |
| data stream | 数据流 | |

## Hierarchical Classification

| English | Chinese | Notes |
|:--------|:--------|:------|
| hierarchical classification | 层次分类 | |
| taxonomy / label hierarchy | 分类体系 / 标签层次结构 | |
| granularity | 粒度 | |
| coarse-grained / fine-grained | 粗粒度 / 细粒度 | |
| coarse-to-fine curriculum | 粗到细课程 | |
| taxonomic tree / label tree | 分类树 / 标签树 | |
| ancestor / descendant | 祖先 / 后裔 | |
| parent class / child class | 父类 / 子类 |
| sibling classes | 兄弟类别 | |
| phylogenetic | 系统发育的 | |
| semantic distance | 语义距离 | |
| mistake severity | 错误严重程度 | |
| multi-label classification | 多标签分类 | |
| multi-granularity | 多粒度 | |

## Methods & Architectures

| English | Chinese | Notes |
|:--------|:--------|:------|
| prototype | 原型 | |
| classifier / classification head | 分类器 / 分类头 | |
| logit | logit | Usually keep English |
| softmax | softmax | Keep English |
| cross-entropy | 交叉熵 | |
| Jensen-Shannon divergence | Jensen-Shannon 散度 | Keep names |
| Kullback-Leibler divergence (KL) | KL 散度 | |
| Shannon entropy | 香农熵 | |
| cosine similarity | 余弦相似度 | |
| margin-based ranking loss | 基于边距的排序损失 | |
| temperature scaling | 温度缩放 | |
| ensemble / aggregation | 集成 / 聚合 | |
| bilevel optimization | 双层优化 | |
| Recursive Least Squares (RLS) | 递归最小二乘 | |
| Fisher Information | Fisher 信息 | |
| ablation study | 消融实验 | |
| sensitivity analysis | 灵敏度分析 | |
| analytic classifier | 解析分类器 | |
| adapter | 适配器 | |
| gate / gating mechanism | 门控 / 门控机制 | |

## Evaluation

| English | Chinese | Notes |
|:--------|:--------|:------|
| benchmark | 基准 / benchmark | |
| baseline | 基线 / baseline | |
| state-of-the-art (SOTA) | 最先进的 / SOTA | |
| Area Under the Curve (AUC) | 曲线下面积 | |
| accuracy | 准确率 | Not "精度" (that's precision) |
| precision | 精确率 / 精度 | |
| recall | 召回率 | |
| F1 score | F1 分数 | |
| standard deviation | 标准差 | |
| confidence interval | 置信区间 | |
| random seed | 随机种子 | |
| held-out set / test set | 保留集 / 测试集 | |
| validation set | 验证集 | |
| train/val/test split | 训练/验证/测试划分 | |

## Common CS Shorthand

| English | Preferred Chinese |
|:--------|:------------------|
| i.e., | 即 |
| e.g., | 例如 |
| w.r.t. | 关于 / 相对于 |
| vs. / versus | 对比 / 与 |
| et al. | 等人 |
| etc. | 等 |
| cf. | 参见 |
| Notably, | 值得注意的是 |
| Specifically, | 具体而言 |
| In contrast, | 相比之下 |
| Therefore, / Thus, | 因此 |
| However, | 然而 |
| Moreover, / Furthermore, | 此外 |
| Consequently, | 因而 |
| In summary, | 总而言之 |

## Style Conventions

1. **Technical terms without good Chinese translations**: Keep English on first use, add Chinese explanation in parentheses. Use English only on subsequent mentions. Examples: "softmax", "logit", "Transformer", "backbone".

2. **Model/method acronyms**: Always keep English. E.g., "HALO", "ResNet", "ViT-B", "CLIP", "DINO".

3. **Dataset names**: Always keep English. E.g., "CIFAR-100", "ImageNet", "iNaturalist".

4. **Mathematical symbols in text**: Never translate. E.g., "Let $x \in \mathbb{R}^d$ be the input..." stays as-is in both English and Chinese sections.

5. **Algorithm names**: Keep English. E.g., "Adam optimizer" → "Adam 优化器", not "亚当优化器".

6. **Author names in citations**: Always English. E.g., "(He et al., 2022)" stays as-is.
