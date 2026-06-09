const fmtUSD = (v) => (v == null ? "—" : `$${Number(v).toFixed(2)}`);
const fmtPct = (v) => (v == null ? "N/A" : `${Number(v).toFixed(1)}%`);

const BADGE = {
  "over-provisioned":  "text-amber-400 bg-amber-950/50 border-amber-800/60",
  "under-provisioned": "text-sky-400 bg-sky-950/50 border-sky-800/60",
  "right-sized":       "text-emerald-400 bg-emerald-950/50 border-emerald-800/60",
  "unknown":           "text-zinc-500 bg-zinc-800/40 border-zinc-700/60",
};

function Badge({ status }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium border ${BADGE[status] || BADGE.unknown}`}>
      {status}
    </span>
  );
}

function UtilBar({ value, low = 20, high = 80 }) {
  if (value == null) return <span className="text-xs text-zinc-700">N/A</span>;
  const pct = Math.min(100, Math.max(0, value));
  const colour = pct < low ? "bg-amber-500" : pct > high ? "bg-sky-500" : "bg-emerald-500";
  return (
    <div className="flex items-center gap-2">
      <div className="w-14 h-1 bg-zinc-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${colour}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-zinc-400">{fmtPct(value)}</span>
    </div>
  );
}

export default function RightsizingTable({ rightsizing }) {
  const totalSavings = rightsizing.reduce((s, r) => s + (r.estimated_monthly_savings_usd || 0), 0);
  const overCount = rightsizing.filter((r) => r.classification === "over-provisioned").length;

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
      <div className="flex items-start justify-between mb-5">
        <div>
          <h2 className="text-sm font-medium text-zinc-200">EC2 Rightsizing</h2>
          <p className="text-xs text-zinc-600 mt-0.5">14-day CloudWatch avg · CPU &lt;20% over · &gt;80% under</p>
        </div>
        <div className="text-right">
          <p className="text-xl font-semibold text-emerald-400 tabular-nums">{fmtUSD(totalSavings)}</p>
          <p className="text-xs text-zinc-600 mt-0.5">est. monthly savings</p>
        </div>
      </div>

      {rightsizing.length === 0 ? (
        <div className="h-32 flex items-center justify-center text-zinc-700 text-sm">
          No running EC2 instances found
        </div>
      ) : (
        <>
          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-800">
                  {["Instance", "Type", "CPU avg", "Mem avg", "Status", "Savings/mo"].map((h, i) => (
                    <th
                      key={h}
                      className={`text-xs font-medium text-zinc-600 uppercase tracking-wide px-2 pb-2.5 ${i >= 4 ? "text-right" : "text-left"}`}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/60">
                {rightsizing.map((r, i) => (
                  <tr key={i} className="hover:bg-zinc-800/30 transition-colors">
                    <td className="px-2 py-3">
                      <p className="font-mono text-xs text-zinc-400">{r.instance_id}</p>
                      <p className="text-xs text-zinc-600 truncate max-w-[120px]" title={r.name}>{r.name}</p>
                    </td>
                    <td className="px-2 py-3 font-mono text-xs text-zinc-400 whitespace-nowrap">{r.instance_type}</td>
                    <td className="px-2 py-3"><UtilBar value={r.avg_cpu_percent} /></td>
                    <td className="px-2 py-3"><UtilBar value={r.avg_memory_percent} /></td>
                    <td className="px-2 py-3 text-right"><Badge status={r.classification} /></td>
                    <td className="px-2 py-3 text-right font-mono text-xs text-emerald-400 whitespace-nowrap">
                      {r.estimated_monthly_savings_usd > 0 ? fmtUSD(r.estimated_monthly_savings_usd) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4 pt-4 border-t border-zinc-800/60 flex flex-wrap gap-6 text-sm">
            <div>
              <p className="text-lg font-semibold text-amber-400 tabular-nums">{overCount}</p>
              <p className="text-xs text-zinc-600 mt-0.5">over-provisioned</p>
            </div>
            <div>
              <p className="text-lg font-semibold text-zinc-300 tabular-nums">{rightsizing.length}</p>
              <p className="text-xs text-zinc-600 mt-0.5">instances evaluated</p>
            </div>
            <div>
              <p className="text-lg font-semibold text-emerald-400 tabular-nums">{fmtUSD(totalSavings)}</p>
              <p className="text-xs text-zinc-600 mt-0.5">potential monthly savings</p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
