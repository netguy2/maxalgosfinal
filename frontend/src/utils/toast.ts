/**
 * Toast utility with alert category support
 *
 * This utility wraps the sonner toast library to provide category-based
 * toast filtering. Toasts are only shown if:
 * 1. Master toasts toggle is enabled
 * 2. The specific category is enabled (if category is specified)
 *
 * Usage:
 * import { showToast } from '@/utils/toast'
 *
 * // With category (respects user settings)
 * showToast.success('Order placed', 'orders')
 * showToast.error('Failed to save', 'strategy')
 *
 * // Without category (always shows if master toggle enabled)
 * showToast.success('Copied to clipboard')
 *
 * // For validation errors (should always show - don't use category)
 * showToast.error('Please fill all required fields')
 */

import { toast } from 'sonner'
import { type AlertCategories, useAlertStore } from '@/stores/alertStore'

type ToastType = 'success' | 'error' | 'warning' | 'info'

interface ToastOptions {
  duration?: number
  description?: string
}

const lastToastTimes = new Map<string, number>()

function cleanErrorMessage(msg: string): string {
  if (!msg) return msg

  let cleaned = msg

  // If message contains market closed: normalize into a single canonical clean format
  if (/market (?:is currently )?closed/i.test(cleaned)) {
    // Extract symbol if present (e.g. NIFTY28JUL2623650CE, RELIANCE, etc.)
    const match = cleaned.match(/([A-Z0-9]{3,30})/i)
    const candidate = match ? match[1].toUpperCase() : ''
    const isRealSymbol =
      candidate &&
      ![
        'ORDER',
        'REJECTED',
        'FAILED',
        'MARKET',
        'ZEBU',
        'ERRORS',
        'LIVE',
        'TRADING',
        'CURRENTLY',
      ].includes(candidate)

    return isRealSymbol
      ? `${candidate}: Market closed (Trading hours: 09:15 AM - 03:30 PM IST)`
      : 'Market closed (Trading hours: 09:15 AM - 03:30 PM IST)'
  }

  // Standardize disconnected / session expired broker messages
  if (/not connected to|session expired/i.test(cleaned)) {
    const brokerMatch = cleaned.match(
      /(zebu|zerodha|angel|fivepaisa|upstox|fyers|dhan|aliceblue|shoonya|flattrade|motilal|bnr|sharekhan)/i
    )
    const bName = brokerMatch ? brokerMatch[1].toUpperCase() : 'Broker'
    return `${bName} session expired. Please re-login in Broker Management or switch to Analyze Mode.`
  }

  // Standardize other order rejection formats
  cleaned = cleaned.replace(/^Order Errors on [^:]+:\s*/i, '')
  cleaned = cleaned.replace(/^Order REJECTED for\s*([\w]+):\s*/i, '$1: ')
  cleaned = cleaned.replace(/^([\w]+):\s*Order\s*(?:Rejected|Failed)\s*\([^)]+\):\s*/i, '$1: ')
  cleaned = cleaned.replace(/^([\w]+):\s*Order\s*(?:Rejected|Failed):\s*/i, '$1: ')

  return cleaned.trim()
}

/**
 * Show a toast notification respecting alert settings
 * @param type - Toast type (success, error, warning, info)
 * @param message - Toast message
 * @param category - Optional category for filtering
 * @param options - Optional toast options
 */
const show = (
  type: ToastType,
  message: string,
  category?: keyof AlertCategories,
  options?: ToastOptions
) => {
  const { shouldShowToast } = useAlertStore.getState()

  if (!shouldShowToast(category)) {
    return
  }

  const cleanedMsg = cleanErrorMessage(message)
  const now = Date.now()
  const key = `${type}:${cleanedMsg}`
  const lastTime = lastToastTimes.get(key) || 0

  // Deduplicate identical/normalized toasts within 3 seconds
  if (now - lastTime < 3000) {
    return
  }

  lastToastTimes.set(key, now)

  // Auto cleanup old keys
  if (lastToastTimes.size > 50) {
    for (const [k, t] of lastToastTimes.entries()) {
      if (now - t > 10000) lastToastTimes.delete(k)
    }
  }

  toast[type](cleanedMsg, {
    id: key,
    ...options,
  })
}

/**
 * Show a success toast
 */
const success = (message: string, category?: keyof AlertCategories, options?: ToastOptions) => {
  show('success', message, category, options)
}

/**
 * Show an error toast
 */
const error = (message: string, category?: keyof AlertCategories, options?: ToastOptions) => {
  show('error', message, category, options)
}

/**
 * Show a warning toast
 */
const warning = (message: string, category?: keyof AlertCategories, options?: ToastOptions) => {
  show('warning', message, category, options)
}

/**
 * Show an info toast
 */
const info = (message: string, category?: keyof AlertCategories, options?: ToastOptions) => {
  show('info', message, category, options)
}

/**
 * Dismiss all toasts
 */
const dismissAll = () => {
  toast.dismiss()
}

/**
 * Show a dynamic toast based on type
 */
const dynamic = (
  type: ToastType,
  message: string,
  category?: keyof AlertCategories,
  options?: ToastOptions
) => {
  show(type, message, category, options)
}

export const showToast = {
  success,
  error,
  warning,
  info,
  dismissAll,
  dynamic,
  show,
}

// Re-export the raw toast for cases where category filtering is not needed
// (e.g., validation errors that must always show)
export { toast }
