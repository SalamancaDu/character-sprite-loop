# 按需使用的提示词与动作设计

这些是提示词骨架，不是固定配方。填入当前角色和用户选定动作，删掉不适用条目。

## 创建角色母版

只有用户提供了参考时才填写参考图片条目；从零创建角色时使用描述，不要求用户补一张尚不存在的角色图。

```text
Use case: stylized-concept
Asset type: transparent full-body character candidate for later animation
Character: [character type, personality and user-specified visual features].
Style: [drawing style, palette and proportions].
Pose: a clear natural full-body pose, with limbs and relevant joints readable,
comfortable margins, and no unnecessary props obscuring the design.
Transparency: real alpha outside the character. Only [intended openings, or none]
are transparent inside it; preserve [opaque eyes, clothing, accessories, etc.].
Constraints: [identity-defining features]. No background, grid, labels or watermark.
```

先展示候选，按用户反馈修改。用户确认之后才将选定图片保存为 `character-master.png`；不能把候选、白底预览或模型自行判断写成“用户已确认”。不强制多视图，多角度仅在用户需求或动作实际需要时补充。

## 角色说明模板

在项目角色目录保存 `character-spec.md`，按实际情况精简，未知内容不要编造：

```markdown
# [角色名称]

- 母版：character-master.png
- 选定依据：[用户确认/直接指定该图制作动作的实际指令]
- 画风与配色：[绘制方式、边缘风格、主要颜色]
- 比例与结构：[头身比例、肢体数量、轮廓与关键特征]
- 透明区域：[背景与设计要求的内部镂空；无内部镂空则写明]
- 实体区域：[需要保留的眼睛、白色/黑色部位、服饰或配件]
- 必须保留：[少量决定角色身份的特征]
```

母版路径相对这份说明解析。为已选定角色生成动作时，实际图片优先于笼统文字；图文有影响造型的冲突时先核对用户选择。新动作的道具、帧数和剧情在当前动作任务中定义，不自动成为角色永久特征。

## 通用透明连续帧

```text
Use case: stylized-concept
Asset type: transparent character animation sprite sheet
Reference: Image 1 is the confirmed character-master.png and defines the exact
character identity, proportions, palette, drawing style and transparency.
Supporting reference, only if supplied: Image 2 is an adjacent pose/keyframe
for motion continuity; it must not override the identity defined by Image 1.
Character requirements: [relevant confirmed features from character-spec.md].
Action: [complete action and intended emotion].
Sequence: [frame-by-frame phases covering execution and recovery].
Layout: exactly [columns] columns × [rows] rows, [N] ordered frames,
read left to right and top to bottom; equal cells and transparent gutters.
Continuity: fixed camera, canvas, character proportions, reference anchors and prop design.
Ground contact: [support-foot baseline; natural flight/body bob, or explicitly grounded motion].
Preserve intentional motion relative to anchors; do not freeze the entire body.
The last-to-first transition continues the same motion without resetting position.
Transparency: real alpha outside the subject and in [specified internal openings].
Preserve [specified solid regions, including any white/black eyes, clothes or props].
No background colors, checkerboard, glow, shadows, labels, grid lines or borders.
Avoid: extra limbs/characters, clipping, detached fragments, unintended facial changes.
```

像素图另加 `crisp coarse square pixels, hard edges, no smoothing`；非像素角色不要强加像素风。简单动作可用上述网格模板；长周期、复杂步态或多角色互动先按下面方式检查关键姿势，再补中间帧。

每次生成都提供已选定母版；只有实际传入相邻帧时才保留辅助参考条目。每张图片的用途及编号必须与本次工具参数中的图片顺序一致。出现造型漂移时，针对差异重申母版特征，不把漂移帧当作新的身份依据。

## 关键姿势与分批补帧

以一次完整左右步态为例，先核对左右脚接触、支撑、摆动和回收等相位；允许自然腾空的奔跑需覆盖腾空阶段。沿用角色自身左右肢体身份，不能每行重新开始一轮动作。多角色还需检查各身份的位置、遮挡和换位顺序。关键姿势由模型检查，只有用户原本指定的节点需要用户审阅。

```text
Reference: Image 1 is the confirmed character master. Images [actual numbers]
are reviewed boundary poses for [phase A] and [phase B], not identity replacements.
Generate [N] chronological in-between poses for [exact interval of the full cycle].
Exclude the supplied endpoints from these N new poses; they will be retained separately.
Track anatomical left/right limbs: [supporting limb, swinging limb and arm opposition].
Preserve the master's proportions and [contact relationships]. Interpolate the intended
pose progression, not a new repeated mini-cycle. Ground motion: [current requirement].
Layout: [small ordered grid or one full-body frame], with sufficient transparent margins.
Use real alpha; preserve [opaque features] and [intended openings].
```

为关键姿势和中间帧分配同一周期中的位置，合并后核对总帧数，避免重复加入端点。末段以最后一个合格姿势到第一个姿势为边界补齐，但不复制第 1 帧作为末帧。

针对性修正先说明实际错误：步态顺序错误则重建受影响相位；比例变化则回到母版；接触脱离则修正受力位置；只有布局问题才调整裁切或间距。同类问题修正后仍存在时缩小批次或逐帧重做，不继续引用整张错误图。只修正当前动作，不擅自重设计角色。

## 调用与阶段示例

- **无参考创建并继续动画**：“先创建一只蓝色像素小猫，确认后制作走路循环。”先生成角色候选并等待确认，不能先做整套动作。
- **修改后确认**：“尾巴短一些，其他保持。”仍在角色设计阶段；展示修改结果。随后用户说“就用这只，继续走路循环”时，保存该版本母版和角色说明，再继续已授权的动画。
- **已有角色直接制作**：“用这张角色做 20 帧挥手循环。”这已指定角色；检查图片并保存/复用母版后进入动作，无需重复索要角色确认。
- **只创建角色**：“创建一个有白眼睛的机器人，只要一张透明 PNG。”保留实体白眼睛，展示角色；确认后交付母版和说明，不添加动画。

## 擦汗并走路

上半身完整动作：手自然下垂 → 抬手 → 靠近额头 → 横向擦拭 → 擦过 → 手离额头 → 放下 → 短暂恢复。下半身跨越整个动作持续交替迈步。保持脚底基线，避免每张图都把手固定在头上。根据手部行程分配帧数，不把 8 帧设为上限。

## 跑着撒钱

腿部维持交替跑步，上半身为取钱 → 蓄力 → 抬臂抛出 → 张手 → 回收手臂。钱沿抛物轨迹向上、向后散开。循环中的纸币应在离开画面后自然补入，或有一致的周期分组；不能全体突然消失。现金颜色沿用用户当前选择或已选资产，无影响需求的歧义时不增加确认，也不套用其他方案的配色。

## 三角色争先跑示例

当用户要求恰好 3 只，彼此靠近，具有纵深，同一地面，贴地奔跑，轮流领先，20 帧循环。轻微大小差可帮助跟踪，避免靠新增颜色标识区分。设计各身份闭合的纵向跑道与前后位置轨迹，换位时不让两只轮廓长时间完全重合。每帧应仍能读出 3 只。若没有足够空间，放宽画布，不靠裁掉角色解决。

针对性修正：`Keep exactly three readable characters in every frame; reduce occlusion only. Preserve character identity, existing running phases, the shared ground plane and the 20-frame action sequence.`

## 角色压杠杆示例

粉色蚂蚁在左端，棕色杆、灰色支点，右端抬起绿色钞票和黄色向上箭头。准备 → 握杆 → 蓄力 → 压下左端 → 右端抬升 → 停顿 → 逐步卸力 → 回到准备。杆绕固定支点旋转，两端反向升降；站立脚固定，手随施力端保持接触，钞票与箭头随远端附着位置移动。放大运动幅度时先检查杆是否撞地、手臂能否够到，不能只改变蚂蚁姿势。

针对性修正：`Increase the actual lever rotation around the fixed fulcrum; keep all object designs and camera unchanged. Maintain hand-to-lever contact and feet grounded; money and arrow remain attached to the far end.`

## 单帧概念和多套方案

用户要先看方案时先交付概念图，避免擅自扩成动画。每套方案独立生成并记录编号与结果路径，按实际语义核对归属后做带编号的联系图；不要按完成时间猜对应关系。用户选中的图优先于早先的方案标题或编号。需要新创作时保留其实际配色、结构和动作含义。
