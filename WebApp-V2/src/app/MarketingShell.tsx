import { Link, Outlet, useLocation } from "react-router-dom";
import { ArrowUpRight, Menu, X } from "lucide-react";
import { useState } from "react";

export function MarketingShell() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const links = [["/products", "产品"], ["/products/qwensci", "QwenSci 预览"], ["/app", "打开工作区"]];
  return <div className="marketing-shell">
    <a className="skip-link" href="#main-content">跳到正文</a>
    <header className="marketing-nav"><Link className="wordmark" to="/"><span className="wordmark-symbol" aria-hidden="true">∞</span><span><strong>QwenSci</strong><small>Evidence-bound research</small></span></Link>
      <button className="mobile-menu" type="button" aria-label={open ? "关闭导航" : "打开导航"} aria-expanded={open} onClick={() => setOpen(!open)}>{open ? <X /> : <Menu />}</button>
      <nav className={open ? "open" : ""} aria-label="主导航">{links.map(([to, label]) => <Link key={to} className={location.pathname === to ? "active" : ""} to={to} onClick={() => setOpen(false)}>{label}</Link>)}<Link className="nav-action" to="/app/full-research/new" onClick={() => setOpen(false)}>启动研究 <ArrowUpRight size={15} /></Link></nav>
    </header>
    <main id="main-content"><Outlet /></main>
    <footer className="marketing-footer"><div><Link className="wordmark" to="/"><span className="wordmark-symbol" aria-hidden="true">∞</span><span><strong>QwenSci</strong><small>Evidence-bound research</small></span></Link><p>把科学问题带入一条可追溯的路径。</p></div><div className="footer-links"><Link to="/products">产品</Link><Link to="/products/qwensci">预览</Link><Link to="/app">工作区</Link><a href="/docs" target="_blank" rel="noreferrer">API 文档 ↗</a></div><small>首发版本 · 单工作区 · 真实状态来自服务端</small></footer>
  </div>;
}
