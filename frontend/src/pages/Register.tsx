import { Check, Loader2, Mail, UserPlus } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { fetchCSRFToken } from '@/api/client'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'

interface PasswordRequirements {
  length: boolean
  uppercase: boolean
  lowercase: boolean
  number: boolean
  special: boolean
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

export default function Register() {
  const navigate = useNavigate()
  const [isLoading, setIsLoading] = useState(false)
  const [isCheckingSetup, setIsCheckingSetup] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState(false)
  const [emailSent, setEmailSent] = useState(true)
  const [submitMessage, setSubmitMessage] = useState('')
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

  // Registration only makes sense once the platform itself has completed
  // initial setup (an admin account exists). If not, bounce to /setup.
  useEffect(() => {
    fetch('/auth/check-setup', { credentials: 'include' })
      .then((res) => res.json())
      .then((data) => {
        if (data.needs_setup) {
          navigate('/setup', { replace: true })
        }
      })
      .catch(() => {})
      .finally(() => setIsCheckingSetup(false))
  }, [navigate])

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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return

    setIsLoading(true)
    setError(null)

    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/auth/register', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({
          username: formData.username,
          email: formData.email,
          password: formData.password,
          confirm_password: formData.confirmPassword,
        }),
      })
      const data = await response.json()

      if (!response.ok || data.status === 'error') {
        setError(data.message || 'Registration failed. Please try again.')
        if (data.redirect) navigate(data.redirect)
        return
      }

      // Backend distinguishes "verification email actually sent" from
      // "account created but SMTP isn't configured / send failed" via
      // email_sent -- never assume success means an email is on its way.
      setEmailSent(data.email_sent !== false)
      setSubmitMessage(data.message || '')
      setSubmitted(true)
    } catch (_err) {
      setError('Registration failed. Please check your connection and try again.')
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

  if (isCheckingSetup) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  if (submitted) {
    return (
      <div className="min-h-screen flex items-center justify-center py-12 px-4">
        <Card className="w-full max-w-md">
          <CardContent className="p-8 text-center space-y-4">
            <div className="flex justify-center">
              <div
                className={cn(
                  'h-14 w-14 rounded-full flex items-center justify-center',
                  emailSent ? 'bg-primary/10' : 'bg-warning/10'
                )}
              >
                <Mail className={cn('h-7 w-7', emailSent ? 'text-primary' : 'text-warning')} />
              </div>
            </div>
            <h1 className="text-2xl font-bold">
              {emailSent ? 'Check your email' : 'Account created'}
            </h1>
            <p className="text-muted-foreground">
              {emailSent ? (
                <>
                  We've sent a verification link to <strong>{formData.email}</strong>. Click it to
                  activate your account, then come back and sign in.
                </>
              ) : (
                submitMessage ||
                "We couldn't send a verification email. Please contact the site administrator to activate your account."
              )}
            </p>
            <Button asChild className="w-full">
              <Link to="/login">Go to Sign In</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center py-12 px-4">
      <div className="container max-w-6xl">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-16 items-center">
          <div className="space-y-6 lg:pr-8">
            <div className="space-y-4">
              <h1 className="text-4xl lg:text-5xl font-bold leading-tight">
                Create your <span className="text-primary">account</span>
              </h1>
              <p className="text-lg lg:text-xl text-muted-foreground leading-relaxed">
                Sign up to access your own Max Algos workspace. We'll send a verification link to
                your email before you can sign in.
              </p>
            </div>
            <p className="text-sm text-muted-foreground">
              Already have an account?{' '}
              <Link to="/login" className="text-primary hover:underline">
                Sign in
              </Link>
            </p>
          </div>

          <div className="w-full">
            <Card>
              <CardContent className="p-6 lg:p-8">
                <form onSubmit={handleSubmit} className="space-y-5">
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
                    <Progress value={passwordStrength} className="h-2" />
                    {strengthInfo.label && (
                      <p className={cn('text-xs font-medium', strengthInfo.color)}>
                        {strengthInfo.label}
                      </p>
                    )}
                  </div>

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

                  <Button type="submit" className="w-full" disabled={!canSubmit || isLoading}>
                    {isLoading ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Creating account...
                      </>
                    ) : (
                      <>
                        <UserPlus className="mr-2 h-4 w-4" />
                        Create Account
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
