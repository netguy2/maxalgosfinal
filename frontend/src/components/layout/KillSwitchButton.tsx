// components/layout/KillSwitchButton.tsx
// Global emergency-stop button for the top nav -- a ONE-SHOT panic button,
// not a toggle. Pressing it immediately cancels all orders, closes all
// positions (across every connected broker -- see
// services/kill_switch_service.py's multi-broker fix), and stops all
// running strategies/flows, then auto-resets back to inactive the moment
// cleanup finishes -- there is no lingering "orders blocked" state to
// remember to turn off. isActive here only reflects a brief in-flight
// window while cleanup is running (or the rare stuck case if cleanup
// crashed mid-sequence), which is what the manual "force clear" deactivate
// dialog below exists for.

import { AlertTriangle, Power } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { type KillSwitchScope, killSwitchApi } from '@/api/killswitch'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { showToast } from '@/utils/toast'

export function KillSwitchButton() {
  const [isActive, setIsActive] = useState(false)
  const [scope, setScope] = useState<KillSwitchScope | null>(null)
  const [showActivateDialog, setShowActivateDialog] = useState(false)
  const [showDeactivateDialog, setShowDeactivateDialog] = useState(false)
  const [confirmation, setConfirmation] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const refreshStatus = useCallback(async () => {
    const state = await killSwitchApi.getStatus()
    if (state) setIsActive(state.kill_switch_active)
  }, [])

  useEffect(() => {
    refreshStatus()
    killSwitchApi.getScope().then(setScope)
  }, [refreshStatus])

  // Reflect activation/deactivation triggered from elsewhere (e.g.
  // another tab, the audit page). The backend emits SocketIO events for
  // this, but there's no shared/exported socket instance in this app to
  // hook into from outside useSocket()'s own effect -- a short poll is a
  // simpler, self-contained way to stay in sync than wiring a new global
  // socket accessor just for this one button.
  useEffect(() => {
    const interval = setInterval(refreshStatus, 15000)
    return () => clearInterval(interval)
  }, [refreshStatus])

  const handleActivate = async () => {
    setIsSubmitting(true)
    try {
      const result = await killSwitchApi.activate()
      if (result.success) {
        // Cleanup already ran and auto-reset server-side by the time this
        // resolves -- refresh from the server rather than assuming
        // isActive=true, since the whole point of the one-shot design is
        // that there's nothing left "active" to reflect.
        await refreshStatus()
        setShowActivateDialog(false)
        showToast.success(
          'Kill switch triggered — all orders cancelled, positions closed',
          'strategy'
        )
      } else {
        showToast.error(result.message || 'Failed to trigger kill switch', 'strategy')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDeactivate = async () => {
    setIsSubmitting(true)
    try {
      const result = await killSwitchApi.deactivate(confirmation)
      if (result.success) {
        setIsActive(false)
        setShowDeactivateDialog(false)
        setConfirmation('')
        showToast.success('Kill switch deactivated', 'strategy')
      } else {
        showToast.error(result.message || 'Failed to deactivate kill switch', 'strategy')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  const scopeDescription = () => {
    const actions: string[] = []
    if (scope?.cancel_orders_enabled ?? true) actions.push('cancel all orders')
    if (scope?.close_positions_enabled ?? true) actions.push('close all positions')
    actions.push('stop all running strategies and automations')
    return actions.join(', ')
  }

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        className={cn('h-8 w-8', isActive && 'text-destructive animate-pulse')}
        onClick={() => (isActive ? setShowDeactivateDialog(true) : setShowActivateDialog(true))}
        title={
          isActive
            ? 'Kill switch cleanup in progress (or stuck — click to force-clear)'
            : 'Emergency stop — cancel orders & close all positions now'
        }
        aria-label={isActive ? 'Force-clear stuck kill switch' : 'Trigger kill switch'}
      >
        <Power className="h-4 w-4" />
      </Button>

      <AlertDialog open={showActivateDialog} onOpenChange={setShowActivateDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="h-5 w-5" />
              Trigger Kill Switch?
            </AlertDialogTitle>
            <AlertDialogDescription>
              This will immediately {scopeDescription()}, across every connected broker, then the
              platform returns to normal — this is a one-time panic action, not a switch you need to
              remember to turn back off. This cannot be undone once cleanup starts. You can adjust
              which actions run by default in Profile → Kill Switch settings.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isSubmitting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleActivate}
              disabled={isSubmitting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {isSubmitting ? 'Triggering…' : 'Trigger Kill Switch'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={showDeactivateDialog}
        onOpenChange={(open) => {
          setShowDeactivateDialog(open)
          if (!open) setConfirmation('')
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Force-Clear Kill Switch</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-3">
                <p>
                  The kill switch normally auto-resets on its own right after cleanup finishes —
                  seeing this means it's stuck active (e.g. cleanup crashed mid-run). This clears
                  the flag WITHOUT running cleanup again. Python strategies and Flow workflows
                  remain stopped after clearing — restart each manually. Type{' '}
                  <span className="font-mono font-bold">UNLOCK</span> to confirm.
                </p>
                <Input
                  value={confirmation}
                  onChange={(e) => setConfirmation(e.target.value)}
                  placeholder="UNLOCK"
                  autoComplete="off"
                />
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isSubmitting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeactivate}
              disabled={isSubmitting || confirmation !== 'UNLOCK'}
            >
              {isSubmitting ? 'Deactivating…' : 'Deactivate'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
