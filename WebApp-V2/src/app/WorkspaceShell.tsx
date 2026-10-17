import { Link, Outlet, useLocation } from "react-router-dom";
import { ChevronLeft, Menu, PanelRight, Settings2 } from "lucide-react";
import { useState } from "react";
import { modules } from "./catalog";

export function WorkspaceShell() {
  const location = useLocation();
  const [navOpen, setNavOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const current = modules.find(item => location.pathname.includes(item.id === "translate" ? "translate" : item.id));
  return <div className="workspace-shell">
    <a className="skip-link" href="#workspace-main">跳到工作区正文</a>
    <header className="workspace-topbar"><button className="icon-button mobile-only" type="button" aria-label="打开工作区导航" onClick={() => setNavOpen(true)}><Menu size={19} /></button><Link className="workspace-brand" to="/"><span className="brand-mark">Q</span><span><strong>QwenSci</strong><small>研究工作区</small></span></Link><div className="workspace-breadcrumb"><Link to="/app">工作区</Link>{current && <><ChevronLeft size={14} /><span>{current.title}</span></>}</div><div className="topbar-actions"><span className="api-indicator"><span /> API 控制面</span><Link className="icon-button" to="/app/preferences" aria-label="研究偏好"><Settings2 size={18} /></Link><button className="icon-button inspector-toggle" type="button" aria-label="打开检查器" onClick={() => setInspectorOpen(true)}><PanelRight size={18} /></button></div></header>
    <div className="workspace-body"><aside className={`workspace-nav ${navOpen ? "open" : ""}`}><div className="nav-mobile-head"><strong>研究模块</strong><button className="icon-button" type="button" aria-label="关闭导航" onClick={() => setNavOpen(false)}>×</button></div><p className="nav-label">研究路径</p>{modules.slice(0, 2).map(item => <Link key={item.id} className={location.pathname.includes(item.id) ? "active" : ""} to={`/app/${item.id}`} onClick={() => setNavOpen(false)}><item.icon size={17} /><span>{item.title}</span></Link>)}<p className="nav-label">独立工具</p>{modules.slice(2, 5).map(item => <Link key={item.id} className={location.pathname.includes(item.id === "translate" ? "translate" : item.id) ? "active" : ""} to={`/app/${item.id}`} onClick={() => setNavOpen(false)}><item.icon size={17} /><span>{item.title}</span></Link>)}<div className="nav-spacer" /><Link className={location.pathname.includes("preferences") ? "active" : ""} to="/app/preferences" onClick={() => setNavOpen(false)}><Settings2 size={17} /><span>研究偏好</span></Link><Link className="back-product" to="/products"><ChevronLeft size={16} /><span>返回产品介绍</span></Link></aside>{navOpen && <button className="nav-scrim" aria-label="关闭导航" onClick={() => setNavOpen(false)} />}
      <main id="workspace-main" className="workspace-main"><Outlet /></main><aside className={`workspace-inspector ${inspectorOpen ? "open" : ""}`}><div className="inspector-mobile-head"><strong>页面检查器</strong><button className="icon-button" type="button" aria-label="关闭检查器" onClick={() => setInspectorOpen(false)}>×</button></div><div className="inspector-default"><span className="inspector-kicker">TRACEABLE BY DESIGN</span><h2>每个结果都留有路径</h2><p>任务状态、输入清单、模型版本和人工决定由服务端保存。页面只负责读取、核对和提交明确动作。</p><div className="trace-line"><span /><span /><span /><span /><span /></div><small>问题 · 证据 · 模型 · 审阅 · 成果</small></div></aside></div>
  </div>;
}
