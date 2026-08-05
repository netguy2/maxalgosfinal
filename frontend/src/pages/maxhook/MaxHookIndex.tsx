import {
  Calendar,
  Check,
  Clock,
  Copy,
  Eye,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Trash2,
  Webhook,
  Zap,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { chartinkApi } from '@/api/chartink'
import { strategyApi } from '@/api/strategy'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { getSignalSourceLabel } from '@/types/strategy'
import { showToast } from '@/utils/toast'

/**
 * A single row in the unified MaxHook connections list. Normalizes the two
 * separate backends (generic Strategy webhook engine + Chartink) into one
 * shape so the UI never has to know which system a row came from, except
 * for `provider`/`kind` (used to build the right webhook URL and route to
 * the right detail page).
 */
interface Connection {
  id: number
  kind: 'strategy' | 'chartink'
  name: string
  platform: string
  webhookId: string
  isActive: boolean
  isIntraday: boolean
  startTime: string | null
  endTime: string | null
  createdAt: string
  /** Comma-separated broker keys this connection trades on (Strategy.brokers).
   * null for chartink-kind rows -- ChartinkStrategy has no brokers column at
   * all (it predates the multi-broker feature), so there is genuinely
   * nothing to show for those, not a fetch failure. */
  brokers: string | null
}

export default function MaxHookIndex() {
  const navigate = useNavigate()
  const [connections, setConnections] = useState<Connection[]>([])
  const [loading, setLoading] = useState(true)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [togglingId, setTogglingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Connection | null>(null)
  const [hostConfig, setHostConfig] = useState<{
    host_server: string
    is_localhost: boolean
  } | null>(null)

  const fetchConnections = async () => {
    try {
      setLoading(true)
      const [strategies, chartinkStrategies] = await Promise.all([
        strategyApi.getStrategies(),
        chartinkApi.getStrategies(),
      ])
      const fromStrategies: Connection[] = strategies
        // "My Strategies" (Visual Builder deployments, marketplace clones)
        // are a different concern from signal connections — exclude them
        // here the same way StrategyIndex's "webhook" filter tab does.
        .filter(
          (s) =>
            s.platform !== 'strategy_builder' && s.signal_source?.toLowerCase() !== 'marketplace'
        )
        .map((s) => ({
          id: s.id,
          kind: 'strategy' as const,
          name: s.name,
          platform: s.platform,
          webhookId: s.webhook_id,
          isActive: s.is_active,
          isIntraday: s.is_intraday,
          startTime: s.start_time,
          endTime: s.end_time,
          createdAt: s.created_at,
          brokers: s.brokers || null,
        }))
      const fromChartink: Connection[] = chartinkStrategies.map((s) => ({
        id: s.id,
        kind: 'chartink' as const,
        name: s.name,
        platform: 'chartink',
        webhookId: s.webhook_id,
        isActive: s.is_active,
        isIntraday: s.is_intraday,
        startTime: s.start_time,
        endTime: s.end_time,
        createdAt: s.created_at,
        brokers: null,
      }))
      setConnections([...fromStrategies, ...fromChartink])
    } catch (_error) {
      showToast.error('Failed to load connections', 'maxhook')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const fetchHostConfig = async () => {
      try {
        const response = await fetch('/api/config/host', { credentials: 'include' })
        const data = await response.json()
        setHostConfig(data)
      } catch (_error) {
        setHostConfig({
          host_server: window.location.origin,
          is_localhost:
            window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1',
        })
      }
    }
    fetchHostConfig()
  }, [])

  // biome-ignore lint/correctness/useExhaustiveDependencies: one-time fetch on mount
  useEffect(() => {
    fetchConnections()
  }, [])

  const getWebhookUrl = (connection: Connection): string => {
    const baseUrl = hostConfig?.host_server || window.location.origin
    const path = connection.kind === 'chartink' ? 'chartink/webhook' : 'strategy/webhook'
    return `${baseUrl}/${path}/${connection.webhookId}`
  }

  const copyWebhookUrl = async (connection: Connection) => {
    const url = getWebhookUrl(connection)
    try {
      await navigator.clipboard.writeText(url)
      setCopiedId(connection.webhookId)
      showToast.success('Webhook URL copied to clipboard', 'clipboard')
      setTimeout(() => setCopiedId(null), 2000)
    } catch {
      showToast.error('Failed to copy URL', 'clipboard')
    }
  }

  const handleToggle = async (connection: Connection) => {
    const key = `${connection.kind}-${connection.id}`
    try {
      setTogglingId(key)
      const response =
        connection.kind === 'chartink'
          ? await chartinkApi.toggleStrategy(connection.id)
          : await strategyApi.toggleStrategy(connection.id)
      if (response.status === 'success') {
        const isActive = response.data?.is_active ?? !connection.isActive
        setConnections((prev) =>
          prev.map((c) =>
            c.kind === connection.kind && c.id === connection.id ? { ...c, isActive } : c
          )
        )
        showToast.success(isActive ? 'Connection resumed' : 'Connection paused', 'maxhook')
      } else {
        showToast.error(response.message || 'Failed to update connection', 'maxhook')
      }
    } catch {
      showToast.error('Failed to update connection', 'maxhook')
    } finally {
      setTogglingId(null)
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    const key = `${deleteTarget.kind}-${deleteTarget.id}`
    try {
      setDeletingId(key)
      const response =
        deleteTarget.kind === 'chartink'
          ? await chartinkApi.deleteStrategy(deleteTarget.id)
          : await strategyApi.deleteStrategy(deleteTarget.id)
      if (response.status === 'success') {
        setConnections((prev) =>
          prev.filter((c) => !(c.kind === deleteTarget.kind && c.id === deleteTarget.id))
        )
        showToast.success('Connection deleted', 'maxhook')
        setDeleteTarget(null)
      } else {
        showToast.error(response.message || 'Failed to delete connection', 'maxhook')
      }
    } catch {
      showToast.error('Failed to delete connection', 'maxhook')
    } finally {
      setDeletingId(null)
    }
  }

  const stats = useMemo(
    () => ({
      total: connections.length,
      active: connections.filter((c) => c.isActive).length,
    }),
    [connections]
  )

  if (loading) {
    return (
      <div className="container mx-auto py-6 space-y-6">
        <div className="flex justify-between items-center">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-10 w-32" />
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Header */}
      <PageHeader
        title="MaxHook"
        description="Receive trading signals from external platforms."
        actions={
          <>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={fetchConnections}>
                <RefreshCw className="h-4 w-4 mr-2" />
                Refresh
              </Button>
              <Button onClick={() => navigate('/maxhook/new')}>
                <Plus className="h-4 w-4 mr-2" />
                New Connection
              </Button>
            </div>
          </>
        }
      />

      {hostConfig?.is_localhost && (
        <Card className="border-loss/40 bg-loss/5">
          <CardContent className="py-4 text-sm">
            <strong>Webhook URLs won't be reachable from the internet.</strong> External platforms
            can't send signals to localhost — use <strong>ngrok</strong>, a{' '}
            <strong>Cloudflare Tunnel</strong>, or a custom domain, and set <code>HOST_SERVER</code>{' '}
            in your <code>.env</code>.
          </CardContent>
        </Card>
      )}

      {connections.length === 0 ? (
        <Card className="py-12">
          <CardContent className="flex flex-col items-center justify-center text-center">
            <Zap className="h-12 w-12 text-muted-foreground mb-4" />
            <h3 className="text-lg font-semibold mb-2">No connections yet</h3>
            <p className="text-muted-foreground mb-4">
              Connect a signal source (TradingView, Chartink, and more) to start trading.
            </p>
            <Button onClick={() => navigate('/maxhook/new')}>
              <Plus className="h-4 w-4 mr-2" />
              New Connection
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {connections.map((connection) => (
            <Card key={`${connection.kind}-${connection.id}`} className="relative overflow-hidden">
              <div
                className={`absolute top-0 left-0 right-0 h-1 ${
                  connection.isActive ? 'bg-profit' : 'bg-muted dark:bg-muted'
                }`}
              />

              <CardHeader className="pb-3">
                <div className="flex items-start justify-between">
                  <div className="space-y-1">
                    <CardTitle className="text-lg">
                      <Link
                        to={`/maxhook/${connection.kind}-${connection.id}`}
                        className="hover:text-primary hover:underline underline-offset-4 transition-colors"
                      >
                        {connection.name}
                      </Link>
                    </CardTitle>
                    <CardDescription>{getSignalSourceLabel(connection.platform)}</CardDescription>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <Badge variant={connection.isActive ? 'default' : 'secondary'}>
                      {connection.isActive ? 'Active' : 'Inactive'}
                    </Badge>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-foreground"
                      title="Edit"
                      aria-label={`Edit ${connection.name}`}
                      onClick={() => navigate(`/maxhook/${connection.kind}-${connection.id}`)}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-foreground"
                      title={connection.isActive ? 'Pause' : 'Resume'}
                      aria-label={
                        connection.isActive
                          ? `Pause ${connection.name}`
                          : `Resume ${connection.name}`
                      }
                      disabled={togglingId === `${connection.kind}-${connection.id}`}
                      onClick={() => handleToggle(connection)}
                    >
                      {connection.isActive ? (
                        <Pause className="h-3.5 w-3.5" />
                      ) : (
                        <Play className="h-3.5 w-3.5" />
                      )}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-loss hover:text-loss hover:bg-loss/10"
                      title="Delete"
                      aria-label={`Delete ${connection.name}`}
                      onClick={() => setDeleteTarget(connection)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              </CardHeader>

              <CardContent className="space-y-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className="font-normal">
                    {connection.isIntraday ? 'Intraday' : 'Positional'}
                  </Badge>
                  {/* chartink-kind connections have no brokers column at all
                  (predates the multi-broker feature) -- showing nothing for
                  them is correct, not a missing fetch. A strategy-kind
                  connection with brokers=null genuinely has no broker
                  selected yet. */}
                  {connection.brokers &&
                    connection.brokers
                      .split(',')
                      .map((b) => b.trim())
                      .filter(Boolean)
                      .map((broker) => (
                        <Badge key={broker} variant="secondary" className="font-normal">
                          {broker}
                        </Badge>
                      ))}
                </div>

                {connection.isIntraday && connection.startTime && (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Clock className="h-4 w-4" />
                    <span>
                      {connection.startTime} - {connection.endTime}
                    </span>
                  </div>
                )}

                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Calendar className="h-3.5 w-3.5" />
                  <span>
                    {new Date(connection.createdAt).toLocaleDateString('en-IN', {
                      day: '2-digit',
                      month: 'short',
                      year: 'numeric',
                    })}{' '}
                    ·{' '}
                    {new Date(connection.createdAt).toLocaleTimeString('en-IN', {
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1 justify-start text-xs font-mono truncate"
                    onClick={() => copyWebhookUrl(connection)}
                  >
                    {copiedId === connection.webhookId ? (
                      <Check className="h-3 w-3 mr-2 text-profit" />
                    ) : (
                      <Copy className="h-3 w-3 mr-2" />
                    )}
                    <span className="truncate">.../{connection.webhookId.slice(0, 8)}...</span>
                  </Button>
                </div>

                <div className="flex gap-2 pt-2">
                  <Button variant="default" size="sm" className="flex-1" asChild>
                    <Link to={`/maxhook/${connection.kind}-${connection.id}`}>
                      <Eye className="h-4 w-4 mr-2" />
                      View
                    </Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Summary footer */}
      <p className="text-xs text-muted-foreground flex items-center gap-1.5">
        <Webhook className="h-3.5 w-3.5" />
        {stats.total} connection{stats.total === 1 ? '' : 's'} · {stats.active} active
      </p>

      <Dialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Connection</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete "{deleteTarget?.name}"? This action cannot be undone.
              All symbol mappings will also be deleted.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={!!deleteTarget && deletingId === `${deleteTarget.kind}-${deleteTarget.id}`}
            >
              {deleteTarget && deletingId === `${deleteTarget.kind}-${deleteTarget.id}`
                ? 'Deleting...'
                : 'Delete Connection'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
