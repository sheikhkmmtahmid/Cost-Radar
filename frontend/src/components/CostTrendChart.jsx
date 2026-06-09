import {
  ComposedChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceDot,
  ResponsiveContainer,
} from "recharts";

const fmtDate = (s) =>
  new Date(s + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });

const fmtUSD = (v) => (v == null ? "—" : `$${Number(v).toFixed(2)}`);

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-zinc-900 border border-zinc-700/60 rounded-lg px-3 py-2.5 shadow-2xl">
      <p className="text-zinc-500 text-xs mb-1">{fmtDate(label)}</p>
      <p className="text-zinc-100 text-sm font-medium tabular-nums">{fmtUSD(payload[0]?.value)}</p>
    </div>
  );
}

export default function CostTrendChart({ costs, anomalies }) {
  const dailyMap = costs.reduce((acc, r) => {
    acc[r.date] = (acc[r.date] || 0) + r.cost_usd;
    return acc;
  }, {});

  const chartData = Object.entries(dailyMap)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, total]) => ({ date, total }));

  const anomalySet = new Set(anomalies.map((a) => a.date));
  const total90d = chartData.reduce((s, d) => s + d.total, 0);
  const avgDay = chartData.length ? total90d / chartData.length : 0;
  const maxCost = chartData.length ? Math.max(...chartData.map((d) => d.total)) : 0;
  const hasSignificantSpend = maxCost >= 0.005;

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 h-full">
      <div className="flex items-start justify-between mb-5">
        <div>
          <h2 className="text-sm font-medium text-zinc-200">Cost Trend</h2>
          <p className="text-xs text-zinc-600 mt-0.5">Daily spend · last 90 days</p>
        </div>
        <div className="text-right">
          <p className="text-xl font-semibold text-zinc-100 tabular-nums">{fmtUSD(total90d)}</p>
          <p className="text-xs text-zinc-600 mt-0.5">avg {fmtUSD(avgDay)}/day</p>
        </div>
      </div>

      {chartData.length === 0 ? (
        <div className="h-52 flex items-center justify-center text-zinc-700 text-sm">
          No cost data — run detection first
        </div>
      ) : !hasSignificantSpend ? (
        <div className="h-52 flex items-center justify-center text-zinc-700 text-sm">
          No significant spend detected (&lt;$0.01 total)
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={chartData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="costFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#6366f1" stopOpacity={0.18} />
                <stop offset="100%" stopColor="#6366f1" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#27272a" vertical={false} strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              tickFormatter={fmtDate}
              tick={{ fill: "#52525b", fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              tickFormatter={(v) => `$${Number(v).toFixed(2)}`}
              tick={{ fill: "#52525b", fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={60}
            />
            <Tooltip content={<ChartTooltip />} cursor={{ stroke: "#3f3f46", strokeWidth: 1 }} />
            <Area
              type="monotone"
              dataKey="total"
              stroke="#6366f1"
              strokeWidth={2}
              fill="url(#costFill)"
              dot={false}
              activeDot={{ r: 4, fill: "#818cf8", strokeWidth: 0 }}
            />
            {chartData
              .filter((d) => anomalySet.has(d.date))
              .map((d) => (
                <ReferenceDot
                  key={d.date}
                  x={d.date}
                  y={d.total}
                  r={4}
                  fill="#f43f5e"
                  stroke="#fda4af"
                  strokeWidth={1.5}
                />
              ))}
          </ComposedChart>
        </ResponsiveContainer>
      )}

      {anomalies.length > 0 && (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-zinc-600">
          <span className="w-2 h-2 rounded-full bg-rose-500 inline-block" />
          {anomalies.length} anomalous {anomalies.length === 1 ? "day" : "days"} flagged
        </p>
      )}
    </div>
  );
}
