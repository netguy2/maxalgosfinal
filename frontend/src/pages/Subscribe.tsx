import { CreditCard, Loader2, LogOut, ShieldCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchCSRFToken } from '@/api/client'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { openSubscriptionCheckout } from '@/lib/razorpay'
import { showToast } from '@/utils/toast'

interface PaymentConfig {
  payments_enabled: boolean
  key_id: string
  subscription_configured: boolean
}

/**
 * Shown when a user is authenticated (password + TOTP already verified)
 * but has no active PlatformSubscription -- the login route returns
 * {status: "subscription_required", redirect: "/subscribe"} in that case.
 * session["user"]/session["logged_in"] are ALREADY set at that point (see
 * blueprints/auth.py login()/login_totp(), both set them before running
 * the subscription-gate check) -- the user has a fully valid app session
 * the whole time they're on this page. What blocks them isn't the
 * session; it's utils/session.py's check_session_validity decorator,
 * which 403s data routes for an unsubscribed non-admin regardless of
 * session validity. Once checkout succeeds and subscription_verify()
 * calls invalidate_subscription_cache(), that gate opens immediately --
 * no re-login is needed or wanted, so success routes straight to
 * /dashboard, not back through /login.
 */
export default function Subscribe() {
  const navigate = useNavigate()
  const [config, setConfig] = useState<PaymentConfig | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/payments/config', { credentials: 'include' })
      .then((res) => res.json())
      .then((data) => setConfig(data.data))
      .catch(() => setConfig(null))
  }, [])

  const handleSubscribe = async () => {
    if (!config) return
    setIsLoading(true)
    setError(null)

    try {
      const csrfToken = await fetchCSRFToken()

      const createRes = await fetch('/payments/subscription/create', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({}),
      })
      const createData = await createRes.json()
      if (!createRes.ok || createData.status !== 'success') {
        setError(createData.message || 'Could not start subscription. Please try again.')
        return
      }

      let checkoutResult
      try {
        checkoutResult = await openSubscriptionCheckout({
          keyId: createData.data.key_id,
          subscriptionId: createData.data.subscription_id,
          name: 'Max Algos',
          description: 'Platform subscription',
        })
      } catch {
        setError('Payment was cancelled.')
        return
      }

      const verifyRes = await fetch('/payments/subscription/verify', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({
          razorpay_subscription_id: checkoutResult.razorpay_subscription_id,
          razorpay_payment_id: checkoutResult.razorpay_payment_id,
          razorpay_signature: checkoutResult.razorpay_signature,
        }),
      })
      const verifyData = await verifyRes.json()

      if (verifyRes.ok && verifyData.status === 'success') {
        showToast.success('Subscription activated')
        navigate('/dashboard')
      } else {
        setError(verifyData.message || 'Subscription verification failed. Please try again.')
      }
    } catch (_err) {
      setError('Something went wrong. Please check your connection and try again.')
    } finally {
      setIsLoading(false)
    }
  }

  const handleLogout = async () => {
    try {
      await fetch('/auth/logout', { method: 'POST', credentials: 'include' })
    } catch {
      // ignore
    }
    navigate('/login')
  }

  return (
    <div className="min-h-screen flex items-center justify-center py-12 px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="flex justify-center mb-2">
            <div className="h-14 w-14 rounded-full bg-primary/10 flex items-center justify-center">
              <ShieldCheck className="h-7 w-7 text-primary" />
            </div>
          </div>
          <CardTitle className="text-2xl">Subscription required</CardTitle>
          <CardDescription>
            Your account is verified, but an active subscription is required to access the
            dashboard.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {config && !config.subscription_configured && (
            <Alert>
              <AlertDescription>
                Subscriptions are not yet configured for this platform. Please contact support.
              </AlertDescription>
            </Alert>
          )}

          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <Button
            className="w-full"
            disabled={!config || !config.payments_enabled || !config.subscription_configured || isLoading}
            onClick={handleSubscribe}
          >
            {isLoading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Processing...
              </>
            ) : (
              <>
                <CreditCard className="mr-2 h-4 w-4" />
                Subscribe now
              </>
            )}
          </Button>

          <Button variant="ghost" className="w-full" onClick={handleLogout} disabled={isLoading}>
            <LogOut className="mr-2 h-4 w-4" />
            Sign out
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
