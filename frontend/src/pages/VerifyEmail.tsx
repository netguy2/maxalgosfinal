import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

type VerifyState = 'verifying' | 'success' | 'error'

export default function VerifyEmail() {
  const [searchParams] = useSearchParams()
  const [state, setState] = useState<VerifyState>('verifying')
  const [message, setMessage] = useState('')
  // Verification tokens are single-use (deleted server-side on success), so
  // a second POST for the same token always looks like "invalid or
  // expired" even though the first one already succeeded. React 19's
  // StrictMode double-invokes effects in dev, and the same link can also
  // get opened in two tabs or re-rendered -- this ref makes sure we only
  // ever fire the request once per token, no matter how many times the
  // effect itself runs.
  const firedForToken = useRef<string | null>(null)

  useEffect(() => {
    const token = searchParams.get('token')
    if (!token) {
      setState('error')
      setMessage('No verification token was provided.')
      return
    }

    if (firedForToken.current === token) {
      return
    }
    firedForToken.current = token

    fetch('/auth/verify-email', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    })
      .then(async (res) => {
        const data = await res.json()
        if (res.ok && data.status === 'success') {
          setState('success')
          setMessage(data.message || 'Email verified.')
        } else {
          setState('error')
          setMessage(data.message || 'Invalid or expired verification link.')
        }
      })
      .catch(() => {
        setState('error')
        setMessage('Something went wrong verifying your email. Please try again.')
      })
  }, [searchParams])

  return (
    <div className="min-h-screen flex items-center justify-center py-12 px-4">
      <Card className="w-full max-w-md">
        <CardContent className="p-8 text-center space-y-4">
          {state === 'verifying' && (
            <>
              <div className="flex justify-center">
                <Loader2 className="h-10 w-10 animate-spin text-primary" />
              </div>
              <h1 className="text-2xl font-bold">Verifying your email...</h1>
            </>
          )}

          {state === 'success' && (
            <>
              <div className="flex justify-center">
                <div className="h-14 w-14 rounded-full bg-success/10 flex items-center justify-center">
                  <CheckCircle2 className="h-7 w-7 text-success" />
                </div>
              </div>
              <h1 className="text-2xl font-bold">Email verified</h1>
              <p className="text-muted-foreground">{message}</p>
              <Button asChild className="w-full">
                <Link to="/login">Go to Sign In</Link>
              </Button>
            </>
          )}

          {state === 'error' && (
            <>
              <div className="flex justify-center">
                <div className="h-14 w-14 rounded-full bg-destructive/10 flex items-center justify-center">
                  <AlertCircle className="h-7 w-7 text-destructive" />
                </div>
              </div>
              <h1 className="text-2xl font-bold">Verification failed</h1>
              <p className="text-muted-foreground">{message}</p>
              <Button asChild variant="outline" className="w-full">
                <Link to="/login">Back to Sign In</Link>
              </Button>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
