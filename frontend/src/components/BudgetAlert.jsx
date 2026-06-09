const fmtUSD = (v) => (v == null ? "—" : `$${Number(v).toFixed(2)}`);

const STATUS = {
  over_budget:  { bar: "bg-rose-500",    text: "text-rose-400",    border: "border-rose-800/60",    bg: "bg-rose-950/30",    label: "Over Budget" },
  at_risk:      { bar: "bg-amber-500",   text: "text-amber-400",   border: "border-amber-800/60",   bg: "bg-amber-950/30",   label: "At Risk" },
  under_budget: { bar: "bg-emerald-500", text: "text-emerald-400", border: "border-emerald-800/60", bg: "bg-emerald-950/30", label: "On Track" },
};

const fmtDate = (s) =>
  s
    ? new Date(s + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })
    : null;

export default function BudgetAlert({ budget }) {
  if (!budget) return null;

  const {
    monthly_budget_usd,
    projected_month_total,
    actual_month_to_date,
    forecast_remaining,
    breach_day,
    overage_usd,
    status,
  } = budget;

  const style = STATUS[status] || STATUS.under_budget;
  const fillPct = Math.min(100, (projected_month_total / monthly_budget_usd) * 100);

  return (
    <div className={`rounded-xl border ${style.border} ${style.bg} p-5`}>
      <div className="flex items-start justify-between mb-4">
        <div>
          <h2 className="text-sm font-medium text-zinc-200">Monthly Budget</h2>
          <p className="text-xs text-zinc-600 mt-0.5">
            Based on actual spend + Prophet forecast
          </p>
        </div>
        <div className="text-right">
          <span className={`text-xs font-medium px-2 py-0.5 rounded-md border ${style.border} ${style.text} ${style.bg}`}>
            {style.label}
          </span>
        </div>
      </div>

      {/* progress bar */}
      <div className="mb-4">
        <div className="flex justify-between text-xs text-zinc-500 mb-1.5">
          <span>Projected month-end spend</span>
          <span className={`font-mono font-semibold ${style.text}`}>
            {fmtUSD(projected_month_total)} / {fmtUSD(monthly_budget_usd)}
          </span>
        </div>
        <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full ${style.bar} transition-all duration-500`}
            style={{ width: `${fillPct}%` }}
          />
        </div>
      </div>

      {/* stat row */}
      <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
        <div>
          <p className="text-zinc-100 font-medium tabular-nums">{fmtUSD(actual_month_to_date)}</p>
          <p className="text-xs text-zinc-600">spent so far</p>
        </div>
        <div>
          <p className="text-zinc-100 font-medium tabular-nums">{fmtUSD(forecast_remaining)}</p>
          <p className="text-xs text-zinc-600">forecast remaining</p>
        </div>
        {overage_usd > 0 && (
          <div>
            <p className={`font-medium tabular-nums ${style.text}`}>+{fmtUSD(overage_usd)}</p>
            <p className="text-xs text-zinc-600">projected overage</p>
          </div>
        )}
        {breach_day && (
          <div>
            <p className={`font-medium ${style.text}`}>{fmtDate(breach_day)}</p>
            <p className="text-xs text-zinc-600">budget breach day</p>
          </div>
        )}
      </div>
    </div>
  );
}
