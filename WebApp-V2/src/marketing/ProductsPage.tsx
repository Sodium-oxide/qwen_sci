import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import { modules } from "../app/catalog";
import { useQuery } from "@tanstack/react-query";
import { client } from "../shared/api";
import { ErrorNotice, Loading, StatusBadge } from "../shared/ui";

export function ProductsPage() {
  const query = useQuery({queryKey: ["modules"], queryFn: ({signal}) => client.modules(signal)});
  return <div className="products-page page-container"><header className="editorial-heading"><p className="eyebrow">QWENSCI / PRODUCT MAP</p><h1>从研究，<br /><em>到科学家手中的工具。</em></h1><p>六个入口，同一条证据边界。先选择你要推进的问题，再决定需要多少自动化。</p></header><ErrorNotice error={query.error} retry={() => void query.refetch()} />{query.isLoading && <Loading label="正在读取产品能力；先展示本地产品目录…" />}<section className="product-list">{modules.map((local, index) => {const remote = query.data?.find(item => item.id === local.id); return <article className="product-chapter" key={local.id}><div className="chapter-number">{String(index + 1).padStart(2, "0")}</div><div className="chapter-copy"><p className="eyebrow">{local.short} / {local.steps.join(" · ")}</p><h2>{local.title}</h2><p>{local.description}</p><div className="chapter-meta"><StatusBadge status={remote?.status || (local.id === "preferences" ? "available" : "partial")} /><span>{local.outcome}</span></div><Link className="text-link" to={`/products/qwensci?module=${local.id}`}>查看产品路径 <ArrowRight size={15} /></Link></div><div className="chapter-visual"><div className={`chapter-art art-${local.id}`}><span>{local.steps.map((step, i) => <i key={step} style={{"--step": i} as React.CSSProperties}>{step}</i>)}</span></div></div></article>;})}</section><div className="boundary-note"><strong>首发能力边界</strong><p>当前版本不提供 R 绘图、参考图编辑、页图翻译、多人认证和原始 PDF 版式重建。页面会以能力接口返回值显示可用状态。</p></div></div>;
}
