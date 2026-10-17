import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { MarketingShell } from "./MarketingShell";
import { WorkspaceShell } from "./WorkspaceShell";
import { RouteErrorBoundary } from "./RouteErrorBoundary";
import { HomePage } from "../marketing/HomePage";
import { ProductsPage } from "../marketing/ProductsPage";
import { QwenSciProductPage } from "../marketing/QwenSciProductPage";
import { WorkspaceHome } from "../modules/workspace/WorkspaceHome";
import { ResearchLaunchPage } from "../modules/research/ResearchLaunchPage";
import { ResearchDetailPage } from "../modules/research/ResearchDetailPage";
import { FigureWorkspace } from "../modules/figure/FigureWorkspace";
import { PolishWorkspace } from "../modules/polish/PolishWorkspace";
import { TranslationWorkspace } from "../modules/translate/TranslationWorkspace";
import { PreferencesPage } from "../modules/preferences/PreferencesPage";
import { App as LegacyResearchApp } from "../App";

export function Router() {
  return <BrowserRouter><RouteErrorBoundary><Routes><Route element={<MarketingShell />}><Route path="/" element={<HomePage />} /><Route path="/products" element={<ProductsPage />} /><Route path="/products/qwensci" element={<QwenSciProductPage />} /></Route><Route path="/app" element={<WorkspaceShell />}><Route index element={<WorkspaceHome />} /><Route path="full-research" element={<ResearchLaunchPage depth="full" />} /><Route path="full-research/new" element={<ResearchLaunchPage depth="full" />} /><Route path="full-research/:runId" element={<ResearchDetailPage />} /><Route path="light-research" element={<ResearchLaunchPage depth="light" />} /><Route path="light-research/new" element={<ResearchLaunchPage depth="light" />} /><Route path="light-research/:runId" element={<ResearchDetailPage />} /><Route path="figure" element={<FigureWorkspace />} /><Route path="figure/new" element={<FigureWorkspace />} /><Route path="figure/:jobId" element={<FigureWorkspace />} /><Route path="polish" element={<PolishWorkspace />} /><Route path="polish/new" element={<PolishWorkspace />} /><Route path="polish/:jobId" element={<PolishWorkspace />} /><Route path="translate" element={<TranslationWorkspace />} /><Route path="translate/new" element={<TranslationWorkspace />} /><Route path="translate/:jobId" element={<TranslationWorkspace />} /><Route path="preferences" element={<PreferencesPage />} /><Route path="legacy" element={<LegacyResearchApp />} /></Route><Route path="*" element={<Navigate to="/" replace />} /></Routes></RouteErrorBoundary></BrowserRouter>;
}
