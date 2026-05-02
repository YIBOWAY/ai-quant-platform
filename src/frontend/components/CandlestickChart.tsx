import type { OhlcvRow } from "@/lib/api";

type CandlestickChartProps = {
  rows: OhlcvRow[];
  height?: number;
};

function priceToY(value: number, min: number, max: number, height: number, padding: number) {
  if (max <= min) {
    return height / 2;
  }
  const plotHeight = height - padding * 2;
  return padding + ((max - value) / (max - min)) * plotHeight;
}

function labelStep(count: number) {
  if (count <= 8) {
    return 1;
  }
  return Math.ceil(count / 8);
}

function shortDate(timestamp: string) {
  return timestamp.slice(5, 10);
}

export function CandlestickChart({ rows, height = 360 }: CandlestickChartProps) {
  if (!rows.length) {
    return null;
  }

  const padding = 28;
  const width = Math.max(760, rows.length * 14);
  const highs = rows.map((row) => row.high);
  const lows = rows.map((row) => row.low);
  const maxPrice = Math.max(...highs);
  const minPrice = Math.min(...lows);
  const step = width / rows.length;
  const candleWidth = Math.max(4, Math.min(10, step * 0.55));
  const tickStep = labelStep(rows.length);

  return (
    <div className="h-[360px] overflow-x-auto rounded border border-border-subtle bg-surface-muted">
      <svg
        aria-label="Historical candlestick chart"
        className="h-full min-w-full"
        preserveAspectRatio="none"
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        <line
          stroke="rgba(148, 163, 184, 0.22)"
          strokeWidth="1"
          x1="0"
          x2={width}
          y1={height - padding}
          y2={height - padding}
        />
        {rows.map((row, index) => {
          const x = index * step + step / 2;
          const highY = priceToY(row.high, minPrice, maxPrice, height, padding);
          const lowY = priceToY(row.low, minPrice, maxPrice, height, padding);
          const openY = priceToY(row.open, minPrice, maxPrice, height, padding);
          const closeY = priceToY(row.close, minPrice, maxPrice, height, padding);
          const up = row.close >= row.open;
          const color = up ? "#10C89B" : "#EF4444";
          const bodyTop = Math.min(openY, closeY);
          const bodyHeight = Math.max(2, Math.abs(closeY - openY));
          const showLabel = index % tickStep === 0 || index === rows.length - 1;

          return (
            <g key={row.timestamp}>
              <line
                stroke={color}
                strokeLinecap="round"
                strokeWidth="1.5"
                x1={x}
                x2={x}
                y1={highY}
                y2={lowY}
              />
              <rect
                fill={color}
                height={bodyHeight}
                rx="1"
                width={candleWidth}
                x={x - candleWidth / 2}
                y={bodyTop}
              />
              {showLabel ? (
                <text
                  fill="#94A3B8"
                  fontFamily="monospace"
                  fontSize="10"
                  textAnchor="middle"
                  x={x}
                  y={height - 8}
                >
                  {shortDate(row.timestamp)}
                </text>
              ) : null}
            </g>
          );
        })}
        <text fill="#94A3B8" fontFamily="monospace" fontSize="10" x="8" y="16">
          H {maxPrice.toFixed(2)}
        </text>
        <text fill="#94A3B8" fontFamily="monospace" fontSize="10" x="8" y={height - 34}>
          L {minPrice.toFixed(2)}
        </text>
      </svg>
    </div>
  );
}
