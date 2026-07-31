/**
 * Some brokers require a single API-key field to actually carry multiple
 * `:::`-joined parts (see broker/<name>/api/auth_api.py, which splits the
 * stored BROKER_API_KEY on "::: "). Asking users to type the separator
 * themselves invites mistakes (wrong order, missing colons, extra spaces).
 *
 * This config describes, per broker, the individual parts that make up
 * that joined string so the UI can render one labeled input per part and
 * join/split them consistently in both BrokerSelect.tsx and Profile.tsx.
 *
 * This only changes how the value is *composed* in the browser - the joined
 * string sent to POST /api/broker/credentials, and every broker's own
 * parsing of BROKER_API_KEY, are unchanged.
 */

export interface MultiPartBrokerConfig {
  /** Ordered field labels, matching the exact order brokers expect. */
  parts: { label: string; placeholder: string }[]
}

export const MULTI_PART_BROKER_CONFIG: Record<string, MultiPartBrokerConfig> = {
  zebu: {
    parts: [
      { label: 'User ID', placeholder: 'e.g. Z56004' },
      { label: 'Client ID', placeholder: 'e.g. Z56004_U' },
    ],
  },
  bnr: {
    parts: [
      { label: 'User ID', placeholder: 'e.g. ITC1441' },
      { label: 'Client ID', placeholder: 'e.g. ITC1441_U' },
    ],
  },
  flattrade: {
    parts: [
      { label: 'Client ID', placeholder: 'Client ID' },
      { label: 'API Key', placeholder: 'API Key' },
    ],
  },
  dhan: {
    parts: [
      { label: 'Client ID', placeholder: 'Client ID' },
      { label: 'API Key', placeholder: 'API Key' },
    ],
  },
  fivepaisa: {
    parts: [
      { label: 'User Key', placeholder: 'User Key' },
      { label: 'User ID', placeholder: 'User ID' },
      { label: 'Client ID', placeholder: 'Client ID' },
    ],
  },
  sharekhan: {
    parts: [
      { label: 'API Key', placeholder: 'API Key' },
      { label: 'Vendor Key (optional)', placeholder: 'Leave blank if not a vendor login' },
    ],
  },
}

export function isMultiPartBroker(brokerId: string): boolean {
  return brokerId in MULTI_PART_BROKER_CONFIG
}

/** Join per-part values into the exact `:::`-separated string the backend expects. */
export function joinBrokerParts(parts: string[]): string {
  return parts.map((p) => p.trim()).join(':::')
}

/**
 * Split an existing `:::`-joined value back into its parts for editing.
 * Pads with empty strings if the stored value has fewer parts than expected
 * (e.g. legacy/partial credentials), so inputs are always controlled.
 */
export function splitBrokerParts(brokerId: string, value: string): string[] {
  const config = MULTI_PART_BROKER_CONFIG[brokerId]
  const count = config?.parts.length ?? 1
  const existing = value ? value.split(':::') : []
  return Array.from({ length: count }, (_, i) => existing[i] ?? '')
}
