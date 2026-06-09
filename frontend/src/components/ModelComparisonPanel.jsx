import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
} from "recharts";

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-zinc-900 border border-zinc-700/60 rounded-lg px-3 py-2.5 shadow-2xl text-xs">
      <p className="text-zinc-400 mb-2 font-medium truncate max-w-[160px]">{label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} style={{ color: p.fill }} className="flex justify-between gap-4">
          <span>{p.name}</span>
          <span className="font-mono font-semibold">{p.value}</span>
        </p>
      ))}
    </div>
  );
}

function StatChip({ label, value, colour }) {
  return (
    <div className="flex flex-col items-center">
      <p className={`text-xl font-semibold tabular-nums ${colour}`}>{value}</p>
      <p className="text-xs text-zinc-600 mt-0.5 text-center">{label}</p>
    </div>
  );
}

export default function ModelComparisonPanel({ comparison }) {
  if (!comparison) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
        <h2 className="text-sm font-medium text-zinc-200 mb-2">Model Comparison</h2>
        <p className="text-zinc-700 text-sm">Run detection to generate comparison data.</p>
      </div>
    );
  }

  const { per_service, total_if, total_z_score, total_consensus, agreement_rate_pct } = comparison;

  // only show services where at least one model flagged something
  const chartData = per_service
    .filter((s) => s.if_count > 0 || s.z_count > 0)
    .map((s) => ({
      name: s.service.replace("Amazon ", "").replace("AWS ", ""),
      "Isolation Forest": s.if_count,
      "Z-Score": s.z_count,
      Consensus: s.consensus_count,
    }));

  // agreement rate drives the colour — low agreement means the models
  // disagree significantly, which is itself a signal worth investigating
  const agreementColour =
    agreement_rate_pct >= 75
      ? "text-emerald-400"
      : agreement_rate_pct >= 50
      ? "text-amber-400"
      : "text-rose-400";

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
      <div className="flex items-start justify-between mb-5">
        <div>
          <h2 className="text-sm font-medium text-zinc-200">Model Comparison</h2>
          <p className="text-xs text-zinc-600 mt-0.5">
            Isolation Forest vs Z-score baseline · per service
          </p>
        </div>
        <div className={`text-right`}>
          <p className={`text-xl font-semibold tabular-nums ${agreementColour}`}>
            {agreement_rate_pct}%
          </p>
          <p className="text-xs text-zinc-600 mt-0.5">agreement rate</p>
        </div>
      </div>

      <div className="flex justify-around mb-5 py-3 border border-zinc-800 rounded-lg">
        <StatChip label="Isolation Forest" value={total_if} colour="text-indigo-400" />
        <div className="w-px bg-zinc-800" />
        <StatChip label="Z-Score" value={total_z_score} colour="text-violet-400" />
        <div className="w-px bg-zinc-800" />
        <StatChip label="Consensus" value={total_consensus} colour="text-rose-400" />
      </div>

      {chartData.length === 0 ? (
        <p className="text-zinc-700 text-sm text-center py-8">
          No anomalies detected — nothing to compare yet.
        </p>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart
              data={chartData}
              margin={{ top: 4, right: 4, left: 0, bottom: 0 }}
              barCategoryGap="30%"
            >
              <CartesianGrid stroke="#27272a" vertical={false} strokeDasharray="3 3" />
              <XAxis
                dataKey="name"
                tick={{ fill: "#52525b", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                allowDecimals={false}
                tick={{ fill: "#52525b", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={24}
              />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
              <Legend
                wrapperStyle={{ fontSize: 11, color: "#71717a", paddingTop: 8 }}
                iconType="circle"
                iconSize={7}
              />
              <Bar dataKey="Isolation Forest" fill="#6366f1" radius={[3, 3, 0, 0]} maxBarSize={20} />
              <Bar dataKey="Z-Score" fill="#8b5cf6" radius={[3, 3, 0, 0]} maxBarSize={20} />
              <Bar dataKey="Consensus" fill="#f43f5e" radius={[3, 3, 0, 0]} maxBarSize={20} />
            </BarChart>
          </ResponsiveContainer>

          <p className="mt-3 text-xs text-zinc-700">
            Consensus (both models agree) = highest confidence. IF-only or Z-score-only detections
            warrant manual review before acting on them.
          </p>
        </>
      )}
    </div>
  );
}
