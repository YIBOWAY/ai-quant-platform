import type { PaperAccountPerformanceSeriesResponse } from "@/lib/api";

type ChartPoint = {
  date: string;
  timestamp: number;
  value: number;
};

const chartStyles: Record<
  string,
  { label: string; stroke: string; dot: string; swatch: string; dash?: string }
> = {
  paper: {
    label: "Paper",
    stroke: "stroke-editorial-accent",
    dot: "fill-editorial-accent",
    swatch: "bg-editorial-accent",
  },
  SPY: {
    label: "SPY",
    stroke: "stroke-editorial-up",
    dot: "fill-editorial-up",
    swatch: "bg-editorial-up",
  },
  QQQ: {
    label: "QQQ",
    stroke: "stroke-ink-secondary",
    dot: "fill-ink-secondary",
    swatch: "bg-ink-secondary",
    dash: "7 5",
  },
};

function normalizeSeries(series: PaperAccountPerformanceSeriesResponse) {
  return series.points
    .map((point) => ({
      date: point.date,
      timestamp: new Date(`${point.date}T00:00:00Z`).getTime(),
      value: point.return_ratio * 100,
    }))
    .filter(
      (point) =>
        point.date.length > 0 &&
        Number.isFinite(point.timestamp) &&
        Number.isFinite(point.value),
    )
    .sort((a, b) => a.timestamp - b.timestamp);
}

function tickDates(dates: string[]) {
  if (dates.length <= 3) {
    return dates;
  }
  const last = dates.length - 1;
  if (dates.length <= 7) {
    return [dates[0], dates[Math.round(last / 2)], dates[last]].filter(
      (value): value is string => Boolean(value),
    );
  }
  return Array.from(
    new Set([
      dates[0],
      dates[Math.round(last / 3)],
      dates[Math.round((last * 2) / 3)],
      dates[last],
    ]),
  ).filter((value): value is string => Boolean(value));
}

export function BriefPerformanceChart({
  ariaLabel,
  emptyLabel,
  series,
}: {
  ariaLabel: string;
  emptyLabel: string;
  series: PaperAccountPerformanceSeriesResponse[];
}) {
  const normalized = series.map((item) => ({
    item,
    points: item.status === "unavailable" ? [] : normalizeSeries(item),
  }));
  const allPoints = normalized.flatMap((item) => item.points);
  if (!allPoints.length) {
    return (
      <div className="flex h-[280px] items-center justify-center border border-editorial-rule bg-paper-surface font-data-mono text-sm text-ink-secondary">
        {emptyLabel}
      </div>
    );
  }

  const width = 820;
  const height = 300;
  const left = 48;
  const right = 20;
  const top = 24;
  const bottom = 48;
  const timestamps = allPoints.map((point) => point.timestamp);
  const minTime = Math.min(...timestamps);
  const maxTime = Math.max(...timestamps);
  const values = allPoints.map((point) => point.value);
  const rawMin = Math.min(0, ...values);
  const rawMax = Math.max(0, ...values);
  const rawSpan = rawMax - rawMin;
  const padding = rawSpan > 0 ? rawSpan * 0.08 : 0.5;
  const minValue = rawMin - padding;
  const maxValue = rawMax + padding;
  const span = maxValue - minValue || 1;
  const xFor = (timestamp: number) =>
    minTime === maxTime
      ? (left + width - right) / 2
      : left + ((timestamp - minTime) / (maxTime - minTime)) * (width - left - right);
  const yFor = (value: number) =>
    height - bottom - ((value - minValue) / span) * (height - top - bottom);
  const polyline = (points: ChartPoint[]) =>
    points
      .map(
        (point) =>
          `${xFor(point.timestamp).toFixed(1)},${yFor(point.value).toFixed(1)}`,
      )
      .join(" ");
  const gridValues = [0, 0.25, 0.5, 0.75, 1].map(
    (ratio) => minValue + span * ratio,
  );
  const dates = Array.from(new Set(allPoints.map((point) => point.date))).sort();
  const dateTicks = tickDates(dates);

  return (
    <div className="border border-editorial-rule bg-paper-surface p-3">
      <div className="mb-2 flex flex-wrap items-center justify-end gap-x-4 gap-y-1 font-data-mono text-[11px]">
        {normalized.map(({ item }) => {
          const style = chartStyles[item.id] ?? chartStyles.paper;
          return (
            <span
              className={item.status === "unavailable" ? "text-ink-secondary" : "text-ink"}
              key={item.id}
            >
              <span
                aria-hidden="true"
                className={`mr-1 inline-block h-0.5 w-5 align-middle ${style.swatch}`}
              />
              {style.label} · {item.status}
            </span>
          );
        })}
      </div>
      <div className="mb-1 text-right font-data-mono text-[10px] text-ink-secondary sm:hidden">
        {minValue.toFixed(1)}% ↔ {maxValue.toFixed(1)}%
      </div>
      <svg
        aria-label={ariaLabel}
        className="h-auto w-full sm:min-h-[250px]"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        {gridValues.map((value) => (
          <g key={value.toFixed(6)}>
            <line
              className="stroke-editorial-rule"
              strokeOpacity="0.65"
              x1={left}
              x2={width - right}
              y1={yFor(value)}
              y2={yFor(value)}
            />
            <text
              className="hidden fill-ink-secondary font-data-mono text-[10px] sm:block"
              textAnchor="end"
              x={left - 8}
              y={yFor(value) + 3}
            >
              {value.toFixed(1)}%
            </text>
          </g>
        ))}
        {normalized.map(({ item, points }) => {
          if (!points.length) {
            return null;
          }
          const style = chartStyles[item.id] ?? chartStyles.paper;
          return (
            <g data-series-id={item.id} key={item.id}>
              {points.length > 1 ? (
                <polyline
                  className={`fill-none ${style.stroke}`}
                  points={polyline(points)}
                  strokeDasharray={style.dash}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={item.id === "paper" ? 2.75 : 2}
                />
              ) : null}
              {points.map((point) => (
                <circle
                  className={style.dot}
                  cx={xFor(point.timestamp)}
                  cy={yFor(point.value)}
                  key={`${item.id}-${point.date}`}
                  r={points.length === 1 ? 4 : 2.25}
                />
              ))}
            </g>
          );
        })}
        {dateTicks.map((dateValue) => {
          const timestamp = new Date(`${dateValue}T00:00:00Z`).getTime();
          return (
            <g key={dateValue}>
              <line
                className="stroke-editorial-rule"
                x1={xFor(timestamp)}
                x2={xFor(timestamp)}
                y1={height - bottom}
                y2={height - bottom + 5}
              />
              <text
                className="hidden fill-ink-secondary font-data-mono text-[10px] sm:block"
                textAnchor={
                  dateValue === dates[0]
                    ? "start"
                    : dateValue === dates.at(-1)
                      ? "end"
                      : "middle"
                }
                x={xFor(timestamp)}
                y={height - 20}
              >
                {dateValue}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="mt-1 flex items-center justify-between gap-2 font-data-mono text-[10px] text-ink-secondary sm:hidden">
        {dateTicks.map((dateValue) => (
          <span className="shrink-0 whitespace-nowrap" key={dateValue}>
            {dateValue}
          </span>
        ))}
      </div>
    </div>
  );
}
