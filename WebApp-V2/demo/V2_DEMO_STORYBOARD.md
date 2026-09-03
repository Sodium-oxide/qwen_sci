# Qwen-Sci WebApp V2 演示剧本

## 演示方法

V2 使用 Chrome DevTools Protocol 自动控制浏览器完成截图，并用 ffmpeg 将截图合成为 16:9 MP4 视频。

特点：

- 中文界面，白色和蓝色风格。
- 展示更强层次感：顶部健康状态、首屏产品叙事、左侧会话、中央编排、右侧成果。
- 全程只生成 dry-run 命令或受保护提示，不触发真实科研运行和数值执行。

## 分镜

1. `V2 首屏指挥舱`：展示 Qwen-Sci V2 的中文定位、白蓝科技感视觉和代表性成果图。
2. `研究启动器`：输入不可变课题、学科、run id、语言和目标页数。
3. `量化模式选择`：展示 “Author 前必须完成量化审阅” 的治理选项。
4. `启动命令预览`：结构化 API 返回 dry-run `qwensci science` 命令。
5. `代表性运行 astr_16`：左侧搜索并选择真实运行，右侧显示 run_dir 与状态。
6. `主流程状态`：Survey、Idea、ExperimentDesign、Author 四阶段状态卡。
7. `数学建模审批链`：展示 Q1/Q2、蓝图、参数、计划、执行授权、结果定性、冻结/修订。
8. `执行保护提示`：点击精确执行按钮后展示必须绑定 plan_identity 的保护提示。
9. `成果与日志筛选`：右侧按 PDF、Figure、Code/Plan、Logs、Quantitative 筛选。
10. `PDF 预览`：展示成果 PDF 可直接内嵌预览。
11. `移动端适配`：展示 V2 在窄屏下仍保持清晰层次。

## 输出

- 截图：`WebApp-V2/demo/screenshots/*.png`
- 视频：`WebApp-V2/demo/qwen-sci-v2-demo.mp4`
