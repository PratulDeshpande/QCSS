import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { setToken } from "./api";
import "./index.css";
import { RegistryProvider } from "./registry";
import { Shell } from "./Shell";
import { WorkbenchProvider } from "./state";
import { Button } from "./ui";
import { Admin } from "./views/Admin";
import { Atlas } from "./views/Atlas";
import { Boards } from "./views/Boards";
import { Chip } from "./views/Chip";
import { ConfigStudio } from "./views/ConfigStudio";
import { Hardware } from "./views/Hardware";
import { LabBench } from "./views/LabBench";
import { Learn } from "./views/Learn";
import { Physics, Program, Timing } from "./views/Pipeline";
import { Readout } from "./views/Readout";
import { Signal } from "./views/Signal";
import { WhatIf } from "./views/WhatIf";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: (n, e: any) => e?.status !== 401 && n < 2, refetchOnWindowFocus: false } },
});

/** Shown when the bridge requires a login token (remote mode). */
function Login() {
  const [t, setT] = useState("");
  return (
    <div className="grid h-full place-items-center">
      <form className="w-80 space-y-3 rounded-lg border border-line bg-s1 p-5"
        onSubmit={(e) => { e.preventDefault(); setToken(t); location.reload(); }}>
        <h1 className="text-[14px] font-semibold">QCSS Explorer — sign in</h1>
        <p className="text-[12px] text-mute">This dashboard runs in remote mode. Enter the token set in QCSS_DASHBOARD_TOKEN on the bridge.</p>
        <input type="password" value={t} onChange={(e) => setT(e.target.value)} aria-label="Dashboard token"
          className="h-8 w-full rounded-md border border-line bg-s2 px-2 text-[12px]" />
        <Button type="submit" kind="primary">Sign in</Button>
      </form>
    </div>
  );
}

function App() {
  const [needsLogin, setNeedsLogin] = useState(false);
  queryClient.getQueryCache().config.onError = (e: any) => { if (e?.status === 401) setNeedsLogin(true); };
  if (needsLogin) return <Login />;
  return (
    <RegistryProvider>
      <WorkbenchProvider>
        <BrowserRouter>
          <Shell>
            <Routes>
              <Route path="/" element={<Atlas />} />
              <Route path="/config" element={<ConfigStudio />} />
              <Route path="/hardware" element={<Hardware />} />
              <Route path="/program" element={<Program />} />
              <Route path="/signal" element={<Signal />} />
              <Route path="/chip" element={<Chip />} />
              <Route path="/physics" element={<Physics />} />
              <Route path="/readout" element={<Readout />} />
              <Route path="/timing" element={<Timing />} />
              <Route path="/boards" element={<Boards />} />
              <Route path="/admin" element={<Admin />} />
              <Route path="/lab" element={<LabBench />} />
              <Route path="/whatif" element={<WhatIf />} />
              <Route path="/learn" element={<Learn />} />
              <Route path="*" element={<div className="text-mute">No such view.</div>} />
            </Routes>
          </Shell>
        </BrowserRouter>
      </WorkbenchProvider>
    </RegistryProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
