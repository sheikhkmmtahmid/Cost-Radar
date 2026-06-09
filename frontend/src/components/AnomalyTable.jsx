import { useState } from "react";

const fmtDate = (s) =>
  new Date(s + "T00:00:00").toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
  });

const fmtUSD = (v) => (v == null ? "—" : `$${Number(v).toFixed(4)}`);

function ModelBadge({ isAnomaly, zFlagged, consensus }) {
  if (consensus) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium border border-rose-700/60 bg-rose-950/50 text-rose-300">
        <span className="w-1.5 h-1.5 rounded-full bg-rose-400 inline-block" />
        Both models
      </span>
    );
  }
  if (isAnomaly) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium border border-orange-700/60 bg-orange-950/50 text-orange-300">
        <span className="w-1.5 h-1.5 rounded-full bg-orange-400 inline-block" />
        IF only
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium border border-yellow-700/60 bg-yellow-950/50 text-yellow-300">
      <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 inline-block" />
      Z-score only
    </span>
  );
}

function ScoreBar({ score }) {
  const pct = Math.min(100, Math.max(0, (score / 0.4) * 100));
  const colour = pct > 75 ? "bg-rose-500" : pct > 45 ? "bg-orange-500" : "bg-amber-400";
  return (
    <div className="flex items-center gap-2">
      <div className="w-14 h-1 bg-zinc-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${colour}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-zinc-400">{Number(score).toFixed(3)}</span>
    </div>
  );
}

function AnomalyRow({ anomaly }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      <tr
        className="hover:bg-zinc-800/30 transition-colors cursor-pointer"
        onClick={() => setExpanded((v) => !v)}
      >
        <td className="px-1 py-2.5">
          <p className="text-zinc-200 text-xs truncate max-w-[130px]" title={anomaly.service}>
            {anomaly.service}
          </p>
        </td>
        <td className="px-2 py-2.5 text-zinc-500 text-xs whitespace-nowrap">
          {fmtDate(anomaly.date)}
        </td>
        <td className="px-1 py-2.5 text-right font-mono text-zinc-300 text-xs whitespace-nowrap">
          {fmtUSD(anomaly.cost_usd)}
        </td>
        <td className="px-2 py-2.5">
          <ScoreBar score={anomaly.anomaly_score} />
        </td>
        <td className="px-2 py-2.5">
          <ModelBadge
            isAnomaly={anomaly.is_anomaly}
            zFlagged={anomaly.z_score_flagged}
            consensus={anomaly.consensus}
          />
        </td>
        <td className="px-1 py-2.5 text-zinc-600 text-xs">
          {expanded ? "▲" : "▼"}
        </td>
      </tr>
      {expanded && anomaly.explanation && (
        <tr className="bg-zinc-800/20">
          <td colSpan={6} className="px-3 py-3">
            <p className="text-xs text-zinc-400 leading-relaxed">{anomaly.explanation}</p>
            <div className="flex gap-4 mt-2 text-xs text-zinc-600">
              {anomaly.historical_mean != null && (
                <span>30d mean: <span className="text-zinc-400 font-mono">{fmtUSD(anomaly.historical_mean)}</span></span>
              )}
              {anomaly.z_score != null && (
                <span>Z-score: <span className="text-zinc-400 font-mono">{Number(anomaly.z_score).toFixed(2)}σ</span></span>
              )}
              {anomaly.percentile != null && (
                <span>Percentile: <span className="text-zinc-400 font-mono">{anomaly.percentile}th</span></span>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function AnomalyTable({ anomalies }) {
  const consensusCount = anomalies.filter((a) => a.consensus).length;
  const ifOnlyCount = anomalies.filter((a) => a.is_anomaly && !a.consensus).length;
  const zOnlyCount = anomalies.filter((a) => a.z_score_flagged && !a.consensus).length;

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 h-full flex flex-col">
      <div className="flex items-start justify-between mb-5">
        <div>
          <h2 className="text-sm font-medium text-zinc-200">Anomalies</h2>
          <p className="text-xs text-zinc-600 mt-0.5">Click a row to see the explanation</p>
        </div>
        <div className="text-right">
          <p className={`text-xl font-semibold tabular-nums ${anomalies.length > 0 ? "text-rose-400" : "text-emerald-400"}`}>
            {anomalies.length}
          </p>
          <p className="text-xs text-zinc-600 mt-0.5">
            {consensusCount} consensus · {ifOnlyCount} IF · {zOnlyCount} Z-score
          </p>
        </div>
      </div>

      {anomalies.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-zinc-700 text-sm">
          No anomalies in latest run
        </div>
      ) : (
        <div className="flex-1 overflow-auto -mx-1">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-800">
                <th className="text-left text-xs font-medium text-zinc-600 uppercase tracking-wide px-1 pb-2">Service</th>
                <th className="text-left text-xs font-medium text-zinc-600 uppercase tracking-wide px-2 pb-2">Date</th>
                <th className="text-right text-xs font-medium text-zinc-600 uppercase tracking-wide px-1 pb-2">Cost</th>
                <th className="text-left text-xs font-medium text-zinc-600 uppercase tracking-wide px-2 pb-2">IF Score</th>
                <th className="text-left text-xs font-medium text-zinc-600 uppercase tracking-wide px-2 pb-2">Detected by</th>
                <th className="px-1 pb-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/60">
              {anomalies.slice(0, 20).map((a, i) => (
                <AnomalyRow key={i} anomaly={a} />
              ))}
            </tbody>
          </table>
          {anomalies.length > 20 && (
            <p className="text-xs text-zinc-700 mt-2 px-1">+{anomalies.length - 20} more</p>
          )}
        </div>
      )}
    </div>
  );
}
