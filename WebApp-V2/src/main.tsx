import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "../app/styles.css";
import "./workspace.css";
import "./styles/tokens.css";
import "./styles/app.css";
import "./styles/marketing.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-serif/400.css";
import "@fontsource/ibm-plex-serif/500.css";
import { Router } from "./app/Router";
import { Providers } from "./app/providers";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Providers><Router /></Providers>
  </StrictMode>,
);
