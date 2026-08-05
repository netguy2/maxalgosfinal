import {
  AlertCircle,
  CheckCircle2,
  Loader2,
  Plug,
  Plus,
  Radio,
  RotateCcw,
  Unplug,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchCSRFToken } from '@/api/client'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
import { Alert, AlertDescription } from '@/components/ui/alert'
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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useAuthStore } from '@/stores/authStore'
import { useBrokerStore } from '@/stores/brokerStore'
import { showToast } from '@/utils/toast'

// Same display-name map used elsewhere for these broker ids.
const BROKER_DISPLAY_NAMES: Record<string, string> = {
  fivepaisa: '5 Paisa',
  fivepaisaxts: '5 Paisa (XTS)',
  aliceblue: 'Alice Blue',
  angel: 'Angel One',
  arrow: 'Arrow',
  compositedge: 'CompositEdge',
  dhan: 'Dhan',
  deltaexchange: 'Delta Exchange',
  indmoney: 'IndMoney',
  dhan_sandbox: 'Dhan (Sandbox)',
  definedge: 'Definedge',
  firstock: 'Firstock',
  flattrade: 'Flattrade',
  motilal: 'Motilal Oswal',
  fyers: 'Fyers',
  ibulls: 'Ibulls',
  iifl: 'IIFL',
  iiflcapital: 'IIFL Capital',
  jainamxts: 'JainamXts',
  pocketful: 'Pocketful',
  rmoney: 'RMoney',
  shoonya: 'Shoonya',
  upstox: 'Upstox',
  wisdom: 'Wisdom Capital',
  zebu: 'Zebu',
  bnr: 'BNR Securities',
  zerodha: 'Zerodha',
}

function brokerLabel(broker: string): string {
  return BROKER_DISPLAY_NAMES[broker] ?? broker
}

interface BrokerConnection {
  broker: string
  configured: boolean
  connected: boolean
  connected_at: string | null
  is_data_broker: boolean
}

export default function BrokerManage() {
  const [connections, setConnections] = useState<BrokerConnection[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyBroker, setBusyBroker] = useState<string | null>(null)
  const [disconnectTarget, setDisconnectTarget] = useState<string | null>(null)
  const [showClearAllConfirm, setShowClearAllConfirm] = useState(false)
  const [clearingAll, setClearingAll] = useState(false)

  const loadConnections = async () => {
    setError(null)
    try {
      const response = await fetch('/api/broker/connections', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') {
        setConnections(data.connections || [])
      } else {
        setError(data.message || 'Failed to load broker connections')
      }
    } catch {
      setError('Failed to load broker connections')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    loadConnections()
    // biome-ignore lint/correctness/useExhaustiveDependencies: loadConnections is stable across renders
  }, [loadConnections])

  const handleSetDataBroker = async (broker: string) => {
    setBusyBroker(broker)
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch(`/api/broker/connections/${broker}/set-data-broker`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        credentials: 'include',
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success(data.message || `${brokerLabel(broker)} is now your data broker`)

        // Sync local session status state immediately so that the top navbar updates
        try {
          const sessionRes = await fetch('/auth/session-status', { credentials: 'include' })
          if (sessionRes.ok) {
            const sessionData = await sessionRes.json()
            if (sessionData.status === 'success' && sessionData.logged_in && sessionData.broker) {
              useAuthStore.getState().setUser({
                username: sessionData.user,
                broker: sessionData.broker,
                isLoggedIn: true,
                loginTime: new Date().toISOString(),
              })
              if (sessionData.api_key) {
                useAuthStore.getState().setApiKey(sessionData.api_key)
              }
              // Update capabilities as well
              await useBrokerStore.getState().fetchCapabilities()
            }
          }
        } catch (syncErr) {
          console.error('Failed to sync session after switching data broker:', syncErr)
        }

        await loadConnections()
      } else {
        showToast.error(data.message || 'Failed to set data broker')
      }
    } catch {
      showToast.error('Failed to set data broker')
    } finally {
      setBusyBroker(null)
    }
  }

  const handleClearAllSessions = async () => {
    setShowClearAllConfirm(false)
    setClearingAll(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/api/broker/connections/clear-all', {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        credentials: 'include',
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success(data.message || 'All broker sessions cleared')
        await loadConnections()
      } else {
        showToast.error(data.message || 'Failed to clear broker sessions')
      }
    } catch {
      showToast.error('Failed to clear broker sessions')
    } finally {
      setClearingAll(false)
    }
  }

  const handleDisconnect = async (broker: string) => {
    setDisconnectTarget(null)
    setBusyBroker(broker)
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch(`/api/broker/connections/${broker}/disconnect`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        credentials: 'include',
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success(data.message || `Disconnected ${brokerLabel(broker)}`)
        await loadConnections()
      } else {
        showToast.error(data.message || 'Failed to disconnect')
      }
    } catch {
      showToast.error('Failed to disconnect')
    } finally {
      setBusyBroker(null)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    )
  }

  return (
    <PageContainer>
      <PageHeader
        title="Broker Management"
        description="Connect multiple broker accounts, pick which one feeds market data, and choose which brokers your orders and strategies execute against."
        icon={<Plug />}
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              className="text-destructive hover:text-destructive"
              disabled={clearingAll || connections.length === 0}
              onClick={() => setShowClearAllConfirm(true)}
            >
              {clearingAll ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <RotateCcw className="mr-2 h-4 w-4" />
              )}
              Clear All Sessions
            </Button>
            <Button asChild>
              <Link to="/broker">
                <Plus className="mr-2 h-4 w-4" />
                Add Broker
              </Link>
            </Button>
          </div>
        }
      />

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {connections.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            <Plug className="h-10 w-10 mx-auto mb-3 opacity-50" />
            <p className="mb-4">No brokers connected yet.</p>
            <Button asChild>
              <Link to="/broker">
                <Plus className="mr-2 h-4 w-4" />
                Connect your first broker
              </Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {connections.map((conn) => (
            <Card key={conn.broker}>
              <CardContent className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 py-4">
                <div className="flex items-center gap-3">
                  <div
                    className={`h-2.5 w-2.5 rounded-full ${
                      conn.connected ? 'bg-profit' : 'bg-muted-foreground/40'
                    }`}
                  />
                  <div>
                    <div className="font-medium flex items-center gap-2 flex-wrap">
                      {brokerLabel(conn.broker)}
                      {conn.is_data_broker && (
                        <Badge variant="secondary" className="gap-1">
                          <Radio className="h-3 w-3" />
                          Data broker
                        </Badge>
                      )}
                      {!conn.connected && conn.configured && (
                        <Badge variant="outline" className="text-muted-foreground">
                          Configured · not connected
                        </Badge>
                      )}
                      {!conn.connected && !conn.configured && (
                        <Badge variant="outline" className="text-muted-foreground">
                          Not set up
                        </Badge>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {conn.connected_at
                        ? `Connected ${new Date(conn.connected_at).toLocaleString()}`
                        : 'Not currently connected'}
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {conn.connected && !conn.is_data_broker && (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busyBroker === conn.broker}
                      onClick={() => handleSetDataBroker(conn.broker)}
                    >
                      {busyBroker === conn.broker ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <>
                          <CheckCircle2 className="mr-2 h-4 w-4" />
                          Set as data broker
                        </>
                      )}
                    </Button>
                  )}
                  {!conn.connected && (
                    <Button variant="default" size="sm" asChild>
                      <Link to={`/broker?broker=${conn.broker}`}>
                        <Plug className="mr-2 h-4 w-4" />
                        {conn.configured ? 'Connect' : 'Set up'}
                      </Link>
                    </Button>
                  )}
                  {conn.connected && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-destructive hover:text-destructive"
                      disabled={busyBroker === conn.broker}
                      onClick={() => setDisconnectTarget(conn.broker)}
                    >
                      <Unplug className="mr-2 h-4 w-4" />
                      Disconnect
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">How this works</CardTitle>
          <CardDescription>
            You can connect as many broker accounts as you like. The{' '}
            <strong>first broker you connect</strong> becomes your data broker and stays that way —
            it alone powers quotes, the option chain, and live prices everywhere in the app, even
            after you connect more brokers. Connecting additional brokers never changes this
            automatically; use <strong>"Set as data broker"</strong> on a connected row if you want
            to switch it. When placing orders or running strategies, you can choose one or more
            connected brokers to send trades to.
          </CardDescription>
        </CardHeader>
      </Card>

      <AlertDialog
        open={!!disconnectTarget}
        onOpenChange={(open) => !open && setDisconnectTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Disconnect {disconnectTarget && brokerLabel(disconnectTarget)}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              This broker will stop receiving orders and, if it is currently your data broker,
              quotes will stop as well until you set another data broker. You can reconnect it again
              later.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => disconnectTarget && handleDisconnect(disconnectTarget)}
            >
              Disconnect
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={showClearAllConfirm} onOpenChange={setShowClearAllConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Clear all broker sessions?</AlertDialogTitle>
            <AlertDialogDescription>
              This disconnects every connected broker and clears the data broker, useful if a
              session has gotten stuck and won't reconnect normally. Your saved API keys/secrets are{' '}
              <strong>not</strong> deleted — you'll be able to reconnect each broker immediately
              from this page without re-entering credentials.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleClearAllSessions}>
              Clear All Sessions
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageContainer>
  )
}
