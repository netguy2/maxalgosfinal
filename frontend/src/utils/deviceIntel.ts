// Session Intelligence: browser-reported device signals sent alongside the
// login request (see blueprints/auth.py's client_hints handling and
// services/session_intelligence_service.py). These are DISPLAY fields for
// the Active Sessions dashboard, not a security signal — a browser can
// misreport any of them, so nothing server-side treats this as trusted
// input beyond "safe to show the user."
//
// Deliberately does NOT do canvas/WebGL/audio fingerprinting or attempt to
// recover the exact physical device model — see
// services/session_intelligence_service.py's module docstring for why.

export interface ClientHints {
  windows_version?: string
  screen_resolution?: string
  timezone?: string
  language?: string
  platform?: string
  hardware_concurrency?: number
  device_memory_gb?: number
}

// navigator.userAgentData is Chromium-only (Chrome/Edge/Opera); Firefox and
// Safari don't implement the User-Agent Client Hints API at all, so this is
// the ONLY way to resolve Windows 10 vs 11 (both report "Windows NT 10.0"
// in the classic User-Agent string).
async function getWindowsVersion(): Promise<string | undefined> {
  const uaData = (
    navigator as {
      userAgentData?: {
        platform?: string
        getHighEntropyValues?: (hints: string[]) => Promise<{ platformVersion?: string }>
      }
    }
  ).userAgentData
  if (!uaData?.platform || uaData.platform !== 'Windows' || !uaData.getHighEntropyValues) {
    return undefined
  }
  try {
    const values = await uaData.getHighEntropyValues(['platformVersion'])
    const majorVersion = values.platformVersion
      ? Number.parseInt(values.platformVersion.split('.')[0], 10)
      : 0
    // Client Hints spec: platformVersion's first component is >= 13 on
    // Windows 11, and 0-10 on Windows 10 and earlier. See
    // https://learn.microsoft.com/microsoft-edge/web-platform/how-to-detect-win11
    return majorVersion >= 13 ? '11' : '10'
  } catch {
    return undefined
  }
}

export async function collectClientHints(): Promise<ClientHints> {
  const hints: ClientHints = {}

  const windowsVersion = await getWindowsVersion()
  if (windowsVersion) hints.windows_version = windowsVersion

  if (typeof screen !== 'undefined' && screen.width && screen.height) {
    hints.screen_resolution = `${screen.width}x${screen.height}`
  }

  try {
    hints.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone
  } catch {
    // Intl unavailable — leave unset
  }

  if (navigator.language) hints.language = navigator.language
  if (navigator.platform) hints.platform = navigator.platform

  if (typeof navigator.hardwareConcurrency === 'number' && navigator.hardwareConcurrency > 0) {
    hints.hardware_concurrency = navigator.hardwareConcurrency
  }

  // deviceMemory is Chromium-only and not in the standard lib.dom.d.ts type
  const deviceMemory = (navigator as { deviceMemory?: number }).deviceMemory
  if (typeof deviceMemory === 'number' && deviceMemory > 0) {
    hints.device_memory_gb = deviceMemory
  }

  return hints
}
