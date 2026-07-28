/**
 * Razorpay Checkout.js loader + Promise wrapper.
 *
 * Checkout.js is Razorpay's hosted payment modal script -- it is loaded
 * on demand (not bundled) since most sessions never open a payment dialog.
 * The client NEVER sees the Razorpay secret key; only the public `key_id`
 * (from GET /payments/config) is used here. Payment success is NOT trusted
 * on its own -- the caller must always POST the returned
 * {razorpay_order_id, razorpay_payment_id, razorpay_signature} to a
 * server-side verify route before treating the payment as real (see
 * blueprints/payments.py).
 */

const CHECKOUT_SRC = 'https://checkout.razorpay.com/v1/checkout.js'

interface RazorpaySuccessResponse {
  razorpay_order_id: string
  razorpay_payment_id: string
  razorpay_signature: string
}

interface RazorpaySubscriptionSuccessResponse {
  razorpay_subscription_id: string
  razorpay_payment_id: string
  razorpay_signature: string
}

interface RazorpayOptions {
  key: string
  amount?: number
  currency?: string
  name: string
  description?: string
  order_id?: string
  subscription_id?: string
  prefill?: { name?: string; email?: string; contact?: string }
  theme?: { color?: string }
  handler: (response: RazorpaySuccessResponse | RazorpaySubscriptionSuccessResponse) => void
  modal?: { ondismiss?: () => void }
}

interface RazorpayInstance {
  open: () => void
  on: (event: string, handler: (response: unknown) => void) => void
}

declare global {
  interface Window {
    Razorpay?: new (options: RazorpayOptions) => RazorpayInstance
  }
}

let loadPromise: Promise<void> | null = null

function loadCheckoutScript(): Promise<void> {
  if (window.Razorpay) return Promise.resolve()
  if (loadPromise) return loadPromise

  loadPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = CHECKOUT_SRC
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => {
      loadPromise = null
      reject(new Error('Failed to load Razorpay Checkout script'))
    }
    document.body.appendChild(script)
  })
  return loadPromise
}

export interface OpenCheckoutParams {
  keyId: string
  orderId: string
  amountPaise: number
  currency: string
  name: string
  description?: string
  prefill?: { name?: string; email?: string; contact?: string }
}

/**
 * Opens the Razorpay Checkout modal and resolves with the raw success
 * response once the user completes payment. Rejects if the script fails to
 * load or the user closes the modal without paying.
 */
export async function openCheckout(
  params: OpenCheckoutParams
): Promise<RazorpaySuccessResponse> {
  await loadCheckoutScript()

  if (!window.Razorpay) {
    throw new Error('Razorpay Checkout failed to initialize')
  }

  return new Promise((resolve, reject) => {
    const rzp = new window.Razorpay!({
      key: params.keyId,
      amount: params.amountPaise,
      currency: params.currency,
      name: params.name,
      description: params.description,
      order_id: params.orderId,
      prefill: params.prefill,
      theme: { color: '#f59e0b' },
      handler: (response) => resolve(response as RazorpaySuccessResponse),
      modal: {
        ondismiss: () => reject(new Error('Payment cancelled')),
      },
    })
    rzp.open()
  })
}

export interface OpenSubscriptionCheckoutParams {
  keyId: string
  subscriptionId: string
  name: string
  description?: string
  prefill?: { name?: string; email?: string; contact?: string }
}

/**
 * Opens the Razorpay Checkout modal for a recurring Subscription (rather
 * than a one-time Order). The plan's amount/currency are defined on the
 * Razorpay Plan itself (see database/settings_db.py
 * platform_subscription_plan_id) -- Checkout does not need `amount` when a
 * `subscription_id` is supplied.
 */
export async function openSubscriptionCheckout(
  params: OpenSubscriptionCheckoutParams
): Promise<RazorpaySubscriptionSuccessResponse> {
  await loadCheckoutScript()

  if (!window.Razorpay) {
    throw new Error('Razorpay Checkout failed to initialize')
  }

  return new Promise((resolve, reject) => {
    const rzp = new window.Razorpay!({
      key: params.keyId,
      name: params.name,
      description: params.description,
      subscription_id: params.subscriptionId,
      prefill: params.prefill,
      theme: { color: '#f59e0b' },
      handler: (response) => resolve(response as RazorpaySubscriptionSuccessResponse),
      modal: {
        ondismiss: () => reject(new Error('Payment cancelled')),
      },
    })
    rzp.open()
  })
}
