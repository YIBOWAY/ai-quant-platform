export function BriefDailyChange({
  className = "",
  value,
}: {
  className?: string;
  value: number | null | undefined;
}) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return (
      <span className={`text-ink-secondary ${className}`.trim()} data-direction="unknown">
        --
      </span>
    );
  }
  if (value === 0) {
    return (
      <span className={`text-ink-secondary ${className}`.trim()} data-direction="flat">
        0.00%
      </span>
    );
  }
  const direction = value > 0 ? "up" : "down";
  const tone = value > 0 ? "text-editorial-up" : "text-editorial-down";
  return (
    <span
      className={`font-semibold ${tone} ${className}`.trim()}
      data-direction={direction}
    >
      {value > 0 ? "+" : "-"}
      {(Math.abs(value) * 100).toFixed(2)}%
    </span>
  );
}
