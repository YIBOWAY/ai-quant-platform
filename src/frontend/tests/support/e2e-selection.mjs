export const E2E_MODES = Object.freeze(["real", "brief", "prefetch", "normal", "degraded", "offline", "empty", "long-content", "lifecycle", "rollback"]);

export function selectE2EArguments(mode, args = []) {
  if (!E2E_MODES.includes(mode)) throw new Error("Unknown isolated E2E mode");
  let explicit = false;
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (/^--grep(?:-invert)?(?:=|$)/.test(arg) || arg === "-g" || !arg.startsWith("-")) { explicit = true; break; }
    if (/^--(?:repeat-each|timeout|max-failures|global-timeout|shard)$/.test(arg)) index += 1;
  }
  const selection = mode === "real" ? "--grep-invert=@combined-fixture|@lifecycle-fixture|@rollback|@live-hermes-sessions|@brief-visual|@production-prefetch"
    : mode === "prefetch" ? "--grep=@production-prefetch" : mode === "brief" ? "--grep=@brief-visual"
      : mode === "lifecycle" ? "--grep=@lifecycle-fixture" : mode === "rollback" ? "--grep=@rollback" : "--grep=@combined-fixture";
  return explicit ? [...args] : [selection, ...args];
}
