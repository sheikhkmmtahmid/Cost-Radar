import { useState, useEffect, useCallback } from "react";
import CostTrendChart from "./components/CostTrendChart";
import AnomalyTable from "./components/AnomalyTable";
import ForecastChart from "./components/ForecastChart";
import RightsizingTable from "./components/RightsizingTable";
import ModelComparisonPanel from "./components/ModelComparisonPanel";
import BudgetAlert from "./components/BudgetAlert";
import "./index.css";

const API_BASE = import.meta.env.VITE_API_URL ?? "/api";

async function apiFetch(path, method = "GET") {
  const res = await fetch(`${API_BASE}${path}`, { method });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

function Logo({ size = 28 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="7" fill="#0d0d1a" />
      <circle cx="16" cy="16" r="10.5" stroke="#4338ca" strokeWidth="1.5" opacity="0.38" />
      <circle cx="16" cy="16" r="5.5" stroke="#6366f1" strokeWidth="1.5" opacity="0.6" />
      <polyline points="7,22 11,17 15,19.5 20,12.5 25,9.5" stroke="#818cf8" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="25" cy="9.5" r="2.2" fill="#a5b4fc" />
    </svg>
  );
}

function Spinner({ small }) {
  const sz = small ? "w-3.5 h-3.5" : "w-8 h-8";
  return <div className={`${sz} border-2 border-zinc-700 border-t-indigo-500 rounded-full animate-spin`} />;
}

function KPICard({ value, label, sub, accent = "text-zinc-100" }) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
      <p className={`text-2xl font-semibold tabular-nums leading-none ${accent}`}>{value}</p>
      <p className="text-sm text-zinc-400 mt-2">{label}</p>
      {sub && <p className="text-xs text-zinc-600 mt-0.5">{sub}</p>}
    </div>
  );
}

export default function App() {
  const [costs, setCosts]           = useState([]);
  const [anomalies, setAnomalies]   = useState([]);
  const [forecast, setForecast]     = useState(null);
  const [comparison, setComparison] = useState(null);
  const [rightsizing, setRightsizing] = useState([]);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState(null);
  const [detecting, setDetecting]   = useState(false);
  const [detectResult, setDetectResult] = useState(null);
  const [lastUpdated, setLastUpdated]   = useState(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [c, a, f, comp, r] = await Promise.all([
        apiFetch("/costs"),
        apiFetch("/anomalies"),
        apiFetch("/forecast"),
        apiFetch("/anomalies/comparison"),
        apiFetch("/rightsizing"),
      ]);
      setCosts(c);
      setAnomalies(a);
      setForecast(f);
      setComparison(comp);
      setRightsizing(r);
      setLastUpdated(new Date());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  const runDetection = async () => {
    setDetecting(true);
    setDetectResult(null);
    try {
      const result = await apiFetch("/detect", "POST");
      setDetectResult({ ok: true, ...result });
      await loadAll();
    } catch (e) {
      setDetectResult({ ok: false, message: e.message });
    } finally {
      setDetecting(false);
    }
  };

  const today          = new Date().toISOString().slice(0, 10);
  const totalSpend     = costs.reduce((s, r) => s + r.cost_usd, 0);
  const totalSavings   = rightsizing.reduce((s, r) => s + (r.estimated_monthly_savings_usd || 0), 0);
  const forecastDays   = (forecast?.points ?? []).filter((p) => p.date > today).length;
  const budgetData     = forecast?.budget ?? null;

  return (
    <div className="min-h-screen bg-[#09090b]">

      <header className="sticky top-0 z-20 border-b border-zinc-800/60 bg-[#09090b]/90 backdrop-blur-md">
        <div className="max-w-[1440px] mx-auto px-4 sm:px-6 h-14 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2.5 shrink-0">
            <Logo />
            <span className="font-semibold text-zinc-100 tracking-tight text-[15px]">CostRadar</span>
          </div>
          <div className="flex items-center gap-2 sm:gap-3">
            {lastUpdated && (
              <span className="hidden md:block text-xs text-zinc-600">
                Updated {lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>
            )}
            <button
              onClick={loadAll}
              disabled={loading}
              className="text-xs text-zinc-400 hover:text-zinc-200 px-3 py-1.5 rounded-lg border border-zinc-800 hover:border-zinc-700 transition-all disabled:opacity-40"
            >
              Refresh
            </button>
            <button
              onClick={runDetection}
              disabled={detecting || loading}
              className="flex items-center gap-2 text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700 px-4 py-1.5 rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {detecting && <Spinner small />}
              {detecting ? "Running…" : "Run Detection"}
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-[1440px] mx-auto px-4 sm:px-6 py-5 space-y-4">

        {detectResult && (
          <div className={`rounded-xl border px-4 py-3 text-sm flex flex-wrap items-center gap-x-5 gap-y-1 ${
            detectResult.ok ? "border-emerald-800/60 bg-emerald-950/30" : "border-rose-800/60 bg-rose-950/30"
          }`}>
            {detectResult.ok ? (
              <>
                <span className="font-medium text-emerald-400">Detection complete</span>
                <span className="text-zinc-400">{detectResult.cost_records_stored} cost records</span>
                <span className="text-rose-400">{detectResult.anomalies_detected} anomalies</span>
                <span className="text-amber-400">{detectResult.alerts_sent} alerts sent</span>
                <span className="text-indigo-400">{detectResult.forecast_points} forecast points</span>
              </>
            ) : (
              <span className="text-rose-400">{detectResult.message}</span>
            )}
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-rose-800/60 bg-rose-950/30 px-4 py-3 flex items-center justify-between gap-4">
            <p className="text-rose-400 text-sm">{error}</p>
            <button onClick={loadAll} className="shrink-0 text-xs text-rose-300 hover:text-white border border-rose-800 hover:border-rose-600 px-3 py-1 rounded-lg transition-all">
              Retry
            </button>
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center h-72"><Spinner /></div>
        ) : (
          <>
            {/* KPI strip */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <KPICard
                value={`$${totalSpend.toFixed(2)}`}
                label="90-day spend"
                sub={`${new Set(costs.map((c) => c.service)).size} services tracked`}
              />
              <KPICard
                value={anomalies.length}
                label="Anomalies flagged"
                sub={`${(comparison?.total_consensus ?? 0)} consensus detections`}
                accent={anomalies.length > 0 ? "text-rose-400" : "text-emerald-400"}
              />
              <KPICard
                value={forecastDays ? `${forecastDays} days` : "—"}
                label="Forecast horizon"
                sub={forecast?.accuracy?.mape != null ? `MAPE ${forecast.accuracy.mape.toFixed(1)}%` : "Prophet model"}
                accent="text-indigo-400"
              />
              <KPICard
                value={`$${totalSavings.toFixed(2)}`}
                label="Est. monthly savings"
                sub="EC2 rightsizing"
                accent="text-emerald-400"
              />
            </div>

            {/* budget alert — full width, only shown when budget is configured */}
            {budgetData && <BudgetAlert budget={budgetData} />}

            {/* cost trend + anomaly table */}
            <div className="grid grid-cols-1 xl:grid-cols-5 gap-4">
              <div className="xl:col-span-3">
                <CostTrendChart costs={costs} anomalies={anomalies} />
              </div>
              <div className="xl:col-span-2">
                <AnomalyTable anomalies={anomalies} />
              </div>
            </div>

            {/* forecast chart */}
            <ForecastChart forecast={forecast} />

            {/* model comparison + rightsizing */}
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              <ModelComparisonPanel comparison={comparison} />
              <RightsizingTable rightsizing={rightsizing} />
            </div>
          </>
        )}
      </main>

      <footer className="mt-6 border-t border-zinc-900 py-5">
        <p className="text-center text-xs text-zinc-700">
          CostRadar · Isolation Forest · Z-Score · Prophet · AWS Cost Explorer · Built by{" "}
          <a
            href="http://skmmt.rootexception.com/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-zinc-500 hover:text-zinc-300 transition-colors underline underline-offset-2"
          >
            SKMMT
          </a>
        </p>
      </footer>
    </div>
  );
}
