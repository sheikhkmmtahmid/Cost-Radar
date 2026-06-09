import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";

const fmtDate = (s) =>
  new Date(s + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });

const fmtUSD = (v) => (v == null ? "—" : `$${Number(v).toFixed(2)}`);

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const yhat   = payload.find((p) => p.dataKey === "yhat");
  const lower  = payload.find((p) => p.dataKey === "yhat_lower");
  const upper  = payload.find((p) => p.dataKey === "yhat_upper");
  return (
    <div className="bg-zinc-900 border border-zinc-700/60 rounded-lg px-3 py-2.5 shadow-2xl min-w-[160px]">
      <p className="text-zinc-500 text-xs mb-1.5">{fmtDate(label)}</p>
      {yhat  && <p className="text-zinc-100 text-sm font-medium tabular-nums">{fmtUSD(yhat.value)}</p>}
      {lower && upper && (
        <p className="text-zinc-600 text-xs mt-1 tabular-nums">
          {fmtUSD(lower.value)} – {fmtUSD(upper.value)}
        </p>
      )}
    </div>
  );
}

function MetricChip({ label, value, sub }) {
  if (value == null) return null;
  return (
    <div className="flex flex-col items-center px-4 py-2 bg-zinc-800/50 rounded-lg border border-zinc-700/40">
      <p className="text-sm font-semibold text-zinc-200 tabular-nums">{value}</p>
      <p className="text-xs text-zinc-500 mt-0.5">{label}</p>
      {sub && <p className="text-xs text-zinc-700">{sub}</p>}
    </div>
  );
}

export default function ForecastChart({ forecast }) {
  const points   = forecast?.points   ?? [];
  const accuracy = forecast?.accuracy ?? null;

  const today    = new Date().toISOString().slice(0, 10);
  const future   = points.filter((p) => p.date > today);
  const projected = future.reduce((s, p) => s + p.yhat, 0);

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
      <div className="flex items-start justify-between mb-5">
        <div>
          <h2 className="text-sm font-medium text-zinc-200">30-Day Forecast</h2>
          <p className="text-xs text-zinc-600 mt-0.5">Prophet · 95% confidence interval</p>
        </div>
        <div className="text-right">
          <p className="text-xl font-semibold text-indigo-400 tabular-nums">{fmtUSD(projected)}</p>
          <p className="text-xs text-zinc-600 mt-0.5">projected next {future.length} days</p>
        </div>
      </div>

      {points.length === 0 ? (
        <div className="h-56 flex items-center justify-center text-zinc-700 text-sm">
          No forecast — run detection to generate
        </div>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={points} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="forecastFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"   stopColor="#6366f1" stopOpacity={0.15} />
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
                tickFormatter={(v) => `$${v}`}
                tick={{ fill: "#52525b", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={50}
              />
              <Tooltip content={<ChartTooltip />} cursor={{ stroke: "#3f3f46", strokeWidth: 1 }} />

              {/* confidence band */}
              <Area type="monotone" dataKey="yhat_upper" stroke="none" fill="url(#forecastFill)" legendType="none" isAnimationActive={false} />
              <Area type="monotone" dataKey="yhat_lower" stroke="none" fill="#09090b"            legendType="none" isAnimationActive={false} />

              <Line
                type="monotone"
                dataKey="yhat"
                stroke="#6366f1"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, fill: "#818cf8", strokeWidth: 0 }}
                legendType="none"
              />
              <ReferenceLine
                x={today}
                stroke="#3f3f46"
                strokeDasharray="4 3"
                label={{ value: "Today", position: "insideTopRight", fill: "#52525b", fontSize: 10 }}
              />
              {/* invisible lines so tooltip shows CI values */}
              <Line dataKey="yhat_upper" stroke="none" dot={false} legendType="none" />
              <Line dataKey="yhat_lower" stroke="none" dot={false} legendType="none" />
            </ComposedChart>
          </ResponsiveContainer>

          {/* accuracy metrics */}
          {accuracy && (
            <div className="mt-4 pt-4 border-t border-zinc-800/60">
              <p className="text-xs text-zinc-600 mb-3">In-sample fit quality</p>
              <div className="flex flex-wrap gap-3">
                <MetricChip
                  label="MAE"
                  value={accuracy.mae != null ? `$${Number(accuracy.mae).toFixed(2)}` : null}
                  sub="mean abs error"
                />
                <MetricChip
                  label="MAPE"
                  value={accuracy.mape != null ? `${Number(accuracy.mape).toFixed(1)}%` : null}
                  sub="mean abs % error"
                />
                <MetricChip
                  label="R²"
                  value={accuracy.r_squared != null ? Number(accuracy.r_squared).toFixed(3) : null}
                  sub="goodness of fit"
                />
                <MetricChip
                  label="Data points"
                  value={accuracy.data_points_used ?? null}
                  sub="training window"
                />
              </div>
            </div>
          )}

          <p className="mt-3 text-xs text-zinc-700">
            Shaded band = 95% confidence interval. Dashed line marks today.
            MAE and MAPE reflect in-sample fit — not out-of-sample forecast error.
          </p>
        </>
      )}
    </div>
  );
}
