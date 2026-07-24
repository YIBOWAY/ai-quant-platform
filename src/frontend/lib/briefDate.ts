const BRIEF_TIME_ZONE = "Asia/Shanghai";

export function briefDateKey(value: Date): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: BRIEF_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(value);
  const read = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value;
  const year = read("year");
  const month = read("month");
  const day = read("day");
  if (!year || !month || !day) {
    throw new Error("Unable to derive the Asia/Shanghai brief date");
  }
  return `${year}-${month}-${day}`;
}
