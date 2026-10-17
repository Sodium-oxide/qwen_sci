import { FlaskConical, ScanLine, ChartNoAxesCombined, Languages, SlidersHorizontal, TextCursorInput } from "lucide-react";
import type { ModuleId } from "../shared/contracts";

export const modules = [
  {id: "full-research", title: "全流程科研", short: "科研", icon: FlaskConical, description: "从课题与证据出发，推进综述、构思、实验设计与写作。", outcome: "研究报告、来源与人工审批记录", steps: ["文献综述", "研究构思", "实验设计", "写作交接"]},
  {id: "light-research", title: "轻度研究", short: "探索", icon: ScanLine, description: "先厘清已有证据和未决问题，再决定下一步研究方向。", outcome: "结构化综述、证据缺口与可选构思", steps: ["文献综述", "可选研究构思"]},
  {id: "figure", title: "科研绘图", short: "绘图", icon: ChartNoAxesCombined, description: "连接数据、变量和图形意图，生成可复核的图与源文件。", outcome: "PNG / SVG / PDF、Python 源文件与 QA", steps: ["绑定数据", "规划图形", "绘制与检查", "人工复核"]},
  {id: "polish", title: "语言润色", short: "润色", icon: TextCursorInput, description: "逐段比较修改，锁定数字、引用与术语，保留作者判断。", outcome: "段落差异、修改理由与审阅后的文档", steps: ["拆分段落", "修订与校验", "逐段复核", "确认与导出"]},
  {id: "translate", title: "论文翻译", short: "翻译", icon: Languages, description: "沿页码和来源文本阅读双语内容，统一术语并逐页确认。", outcome: "双语文本、术语表与来源页映射", steps: ["解析 PDF", "逐块翻译", "逐页复核", "文本结构导出"]},
  {id: "preferences", title: "研究偏好", short: "偏好", icon: SlidersHorizontal, description: "保存默认模型、语言、输出与隐私设置，减少重复配置。", outcome: "带版本的工作区设置，应用于新任务", steps: ["读取设置", "编辑草稿", "核对版本", "保存"]},
] satisfies Array<{id: ModuleId; title: string; short: string; icon: typeof FlaskConical; description: string; outcome: string; steps: string[]}>;
export const findModule = (id: string) => modules.find(module => module.id === id);
