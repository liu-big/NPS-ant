export const DEFAULT_PORT_RANGES = {
  ssh: { start: 18023, end: 18522 },
  web: { start: 18523, end: 19022 },
  gdb: { start: 19023, end: 19522 },
  temp: { start: 19523, end: 20022 }
}

export function resolvePortRanges(configRanges) {
  if (!configRanges || typeof configRanges !== 'object') {
    return { ...DEFAULT_PORT_RANGES }
  }
  const merged = { ...DEFAULT_PORT_RANGES }
  for (const [service, range] of Object.entries(configRanges)) {
    if (range?.start != null && range?.end != null) {
      merged[service] = { start: range.start, end: range.end }
    }
  }
  return merged
}

export function isPortValid(service, port, ranges = DEFAULT_PORT_RANGES) {
  const p = Number(port)
  if (!Number.isFinite(p) || p <= 0) return false
  const range = ranges[service] || DEFAULT_PORT_RANGES[service]
  if (!range) return false
  return p >= range.start && p <= range.end
}

export function portDisplay(service, port, portValid) {
  if (portValid === false || !isPortValid(service, port)) {
    return '端口异常'
  }
  return String(port)
}
