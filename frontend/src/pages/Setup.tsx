import { Check, Info, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchCSRFToken } from '@/api/client'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { openCheckout } from '@/lib/razorpay'
import { cn } from '@/lib/utils'
import { showToast } from '@/utils/toast'

interface PasswordRequirements {
  length: boolean
  uppercase: boolean
  lowercase: boolean
  number: boolean
  special: boolean
}

interface PaymentConfig {
  payments_enabled: boolean
  key_id: string
  currency: string
  setup_fee_paise: number
}

function calculatePasswordStrength(password: string): number {
  let score = 0
  if (password.length >= 8) score += 20
  if (password.length >= 12) score += 10
  if (password.length >= 16) score += 10
  if (/[A-Z]/.test(password)) score += 15
  if (/[a-z]/.test(password)) score += 15
  if (/[0-9]/.test(password)) score += 15
  if (/[!@#$%^&*]/.test(password)) score += 15
  return score
}

function checkPasswordRequirements(password: string): PasswordRequirements {
  return {
    length: password.length >= 8,
    uppercase: /[A-Z]/.test(password),
    lowercase: /[a-z]/.test(password),
    number: /[0-9]/.test(password),
    special: /[!@#$%^&*]/.test(password),
  }
}

export default function Setup() {
  const navigate = useNavigate()
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [paymentConfig, setPaymentConfig] = useState<PaymentConfig | null>(null)
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    password: '',
    confirmPassword: '',
  })
  const [requirements, setRequirements] = useState<PasswordRequirements>({
    length: false,
    uppercase: false,
    lowercase: false,
    number: false,
    special: false,
  })
  const [passwordStrength, setPasswordStrength] = useState(0)

  useEffect(() => {
    const reqs = checkPasswordRequirements(formData.password)
    setRequirements(reqs)
    setPasswordStrength(calculatePasswordStrength(formData.password))
  }, [formData.password])

  useEffect(() => {
    fetch('/payments/config', { credentials: 'include' })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => setPaymentConfig(data))
      .catch(() => setPaymentConfig(null))
  }, [])

  const allRequirementsMet = Object.values(requirements).every(Boolean)
  const passwordsMatch = formData.password === formData.confirmPassword
  const allFieldsFilled = Object.values(formData).every((v) => v.trim() !== '')
  const canSubmit = allRequirementsMet && passwordsMatch && allFieldsFilled

  const getStrengthLabel = () => {
    if (passwordStrength >= 80) return { label: 'Strong', color: 'text-success' }
    if (passwordStrength >= 50) return { label: 'Medium', color: 'text-warning' }
    if (passwordStrength > 0) return { label: 'Weak', color: 'text-destructive' }
    return { label: '', color: '' }
  }

  const strengthInfo = getStrengthLabel()

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target
    setFormData((prev) => ({ ...prev, [name]: value }))
  }

  const finishAndRedirect = async () => {
    showToast.success('Account created successfully')
    try {
      await fetch('/auth/logout', { method: 'POST', credentials: 'include' })
    } catch {
      // Ignore logout errors
    }
    navigate('/login')
  }

  // Legacy direct-submit path — used when payments are disabled by the admin
  // (or unconfigured), so non-interactive/Docker installs keep working.
  const submitDirect = async () => {
    const csrfToken = await fetchCSRFToken()

    const form = new FormData()
    form.append('username', formData.username)
    form.append('email', formData.email)
    form.append('password', formData.password)
    form.append('confirm_password', formData.confirmPassword)
    form.append('csrf_token', csrfToken)

    const response = await fetch('/setup', {
      method: 'POST',
      body: form,
      credentials: 'include',
    })
    await response.text()

    if (response.ok || response.redirected) {
      await finishAndRedirect()
    } else {
      setError('Setup failed. Please try again.')
    }
  }

  // Paid path — create a Razorpay order for the setup fee, open Checkout,
  // and only create the account after the backend verifies the signature.
  const submitWithPayment = async (config: PaymentConfig) => {
    const csrfToken = await fetchCSRFToken()

    const orderRes = await fetch('/payments/setup/create-order', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
      body: JSON.stringify({}),
    })
    const orderData = await orderRes.json()
    if (!orderRes.ok) {
      setError(orderData.message || 'Could not start payment. Please try again.')
      return
    }

    let checkoutResult
    try {
      checkoutResult = await openCheckout({
        keyId: config.key_id,
        orderId: orderData.order_id,
        amountPaise: orderData.amount,
        currency: orderData.currency,
        name: 'Max Algos',
        description: 'Installation activation fee',
        prefill: { email: formData.email },
      })
    } catch {
      setError('Payment was cancelled.')
      return
    }

    const verifyRes = await fetch('/payments/setup/verify', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
      body: JSON.stringify({
        razorpay_order_id: checkoutResult.razorpay_order_id,
        razorpay_payment_id: checkoutResult.razorpay_payment_id,
        razorpay_signature: checkoutResult.razorpay_signature,
        username: formData.username,
        email: formData.email,
        password: formData.password,
      }),
    })
    const verifyData = await verifyRes.json()

    if (verifyRes.ok && verifyData.status === 'success') {
      await finishAndRedirect()
    } else {
      setError(verifyData.message || 'Payment verification failed. Please try again.')
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return

    setIsLoading(true)
    setError(null)

    try {
      if (paymentConfig?.payments_enabled) {
        await submitWithPayment(paymentConfig)
      } else {
        await submitDirect()
      }
    } catch (_err) {
      setError('Setup failed. Please check your connection and try again.')
    } finally {
      setIsLoading(false)
    }
  }

  const RequirementItem = ({ met, children }: { met: boolean; children: React.ReactNode }) => (
    <div
      className={cn(
        'flex items-center gap-2 text-sm py-1 transition-colors',
        met ? 'text-success' : 'text-muted-foreground'
      )}
    >
      <Check className={cn('h-4 w-4', met ? 'opacity-100' : 'opacity-0')} />
      <span>{children}</span>
    </div>
  )

  const setupFeeRupees = paymentConfig
    ? (paymentConfig.setup_fee_paise / 100).toLocaleString('en-IN')
    : null

  return (
    <div className="min-h-screen bg-background flex items-center justify-center py-12 px-4">
      <div className="container max-w-6xl">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-16 items-center">
          {/* Left side content */}
          <div className="space-y-6 lg:pr-8">
            <div className="space-y-4">
              <h1 className="text-4xl lg:text-5xl font-bold leading-tight">
                Initial <span className="text-primary">Setup</span>
              </h1>
              <p className="text-lg lg:text-xl text-muted-foreground leading-relaxed">
                Welcome to Max Algos! Create your administrator account to get started with
                algorithmic trading. This account will have full access to manage the platform.
              </p>
            </div>

            <Alert>
              <Info className="h-5 w-5" />
              <AlertDescription>
                <strong className="block mb-1">First Time Setup</strong>
                {paymentConfig?.payments_enabled ? (
                  <>
                    A one-time activation fee of ₹{setupFeeRupees} is required to create your
                    administrator account. After signing in, open your Profile and scan the TOTP
                    QR code there to enable two-factor authentication and TOTP-based password
                    resets.
                  </>
                ) : (
                  <>
                    This form will create the initial administrator account. After signing in,
                    open your Profile and scan the TOTP QR code there to enable two-factor
                    authentication and TOTP-based password resets.
                  </>
                )}
              </AlertDescription>
            </Alert>
          </div>

          {/* Right side setup form */}
          <div className="w-full">
            <Card>
              <CardContent className="p-6 lg:p-8">
                <form onSubmit={handleSubmit} className="space-y-5">
                  {/* Username */}
                  <div className="space-y-2">
                    <Label htmlFor="username">Username</Label>
                    <Input
                      id="username"
                      name="username"
                      type="text"
                      placeholder="Choose a username"
                      value={formData.username}
                      onChange={handleInputChange}
                      required
                      disabled={isLoading}
                      autoComplete="username"
                    />
                  </div>

                  {/* Email */}
                  <div className="space-y-2">
                    <Label htmlFor="email">Email</Label>
                    <Input
                      id="email"
                      name="email"
                      type="email"
                      placeholder="Enter your email"
                      value={formData.email}
                      onChange={handleInputChange}
                      required
                      disabled={isLoading}
                    />
                  </div>

                  {/* Password */}
                  <div className="space-y-2">
                    <Label htmlFor="password">Password</Label>
                    <Input
                      id="password"
                      name="password"
                      type="password"
                      placeholder="Choose a password"
                      value={formData.password}
                      onChange={handleInputChange}
                      required
                      disabled={isLoading}
                      autoComplete="new-password"
                    />
                    {/* Password Strength Meter */}
                    <Progress value={passwordStrength} className="h-2" />
                    {strengthInfo.label && (
                      <p className={cn('text-xs font-medium', strengthInfo.color)}>
                        {strengthInfo.label}
                      </p>
                    )}
                  </div>

                  {/* Confirm Password */}
                  <div className="space-y-2">
                    <Label htmlFor="confirmPassword">Confirm Password</Label>
                    <Input
                      id="confirmPassword"
                      name="confirmPassword"
                      type="password"
                      placeholder="Confirm your password"
                      value={formData.confirmPassword}
                      onChange={handleInputChange}
                      required
                      disabled={isLoading}
                      autoComplete="new-password"
                    />
                    {formData.confirmPassword && (
                      <p
                        className={cn(
                          'text-xs',
                          passwordsMatch ? 'text-success' : 'text-destructive'
                        )}
                      >
                        {passwordsMatch ? 'Passwords match' : 'Passwords do not match'}
                      </p>
                    )}
                  </div>

                  {/* Password Requirements */}
                  <div className="bg-muted rounded-lg p-4 space-y-1">
                    <RequirementItem met={requirements.length}>
                      Minimum 8 characters
                    </RequirementItem>
                    <RequirementItem met={requirements.uppercase}>
                      At least 1 uppercase letter (A-Z)
                    </RequirementItem>
                    <RequirementItem met={requirements.lowercase}>
                      At least 1 lowercase letter (a-z)
                    </RequirementItem>
                    <RequirementItem met={requirements.number}>
                      At least 1 number (0-9)
                    </RequirementItem>
                    <RequirementItem met={requirements.special}>
                      At least 1 special character (!@#$%^&*)
                    </RequirementItem>
                  </div>

                  {error && (
                    <Alert variant="destructive">
                      <AlertDescription>{error}</AlertDescription>
                    </Alert>
                  )}

                  {/* Submit Button */}
                  <Button type="submit" className="w-full" disabled={!canSubmit || isLoading}>
                    {isLoading ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        {paymentConfig?.payments_enabled ? 'Processing...' : 'Creating Account...'}
                      </>
                    ) : (
                      <>
                        <Check className="mr-2 h-4 w-4" />
                        {paymentConfig?.payments_enabled
                          ? `Pay ₹${setupFeeRupees} & Create Account`
                          : 'Create Account'}
                      </>
                    )}
                  </Button>
                </form>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  )
}
