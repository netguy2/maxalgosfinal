import {
  AlertTriangle,
  ArrowLeft,
  ArrowLeftRight,
  Check,
  Clock,
  Code,
  Copy,
  Info,
  Pause,
  Pencil,
  Play,
  Power,
  Settings,
  Trash2,
  TrendingDown,
  TrendingUp,
  Webhook,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { chartinkApi } from '@/api/chartink'
import { strategyApi } from '@/api/strategy'
import { DeliveryLogPanel } from '@/components/maxhook/DeliveryLogPanel'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
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
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { ChartinkStrategy, ChartinkSymbolMapping } from '@/types/chartink'
import { getSignalSourceLabel, type Strategy, type StrategySymbolMapping } from '@/types/strategy'
import { showToast } from '@/utils/toast'

type Kind = 'strategy' | 'chartink'

/** A normalized view of either backend's row — only the fields this page
 * actually renders, so the JSX below never has to branch on which backend
 * a field came from. */
interface ConnectionDetail {
  id: number
  kind: Kind
  name: string
  platform: string
  webhookId: string
  isActive: boolean
  isIntraday: boolean
  tradingMode: string | null
  startTime: string | null
  endTime: string | null
  squareoffTime: string | null
  createdAt: string
}

interface MappingRow {
  id: number
  symbol: string
  exchange: string
  quantity: number
  productType: string
  isActive: boolean
}

function normalizeStrategy(s: Strategy): ConnectionDetail {
  return {
    id: s.id,
    kind: 'strategy',
    name: s.name,
    platform: s.platform,
    webhookId: s.webhook_id,
    isActive: s.is_active,
    isIntraday: s.is_intraday,
    tradingMode: s.trading_mode,
    startTime: s.start_time,
    endTime: s.end_time,
    squareoffTime: s.squareoff_time,
    createdAt: s.created_at,
  }
}

function normalizeChartink(s: ChartinkStrategy): ConnectionDetail {
  return {
    id: s.id,
    kind: 'chartink',
    name: s.name,
    platform: 'chartink',
    webhookId: s.webhook_id,
    isActive: s.is_active,
    isIntraday: s.is_intraday,
    tradingMode: null,
    startTime: s.start_time,
    endTime: s.end_time,
    squareoffTime: s.squareoff_time,
    createdAt: s.created_at,
  }
}

function normalizeStrategyMapping(m: StrategySymbolMapping): MappingRow {
  return {
    id: m.id,
    symbol: m.symbol,
    exchange: m.exchange,
    quantity: m.quantity,
    productType: m.product_type,
    isActive: m.is_active,
  }
}

// chartink mappings have no per-symbol pause/resume -- ChartinkSymbolMapping
// has no is_active column at all (only the whole connection can be
// paused). Always "active" here is correct, not a stand-in for missing
// data -- the Pause/Resume button is hidden for chartink-kind rows below.
function normalizeChartinkMapping(m: ChartinkSymbolMapping): MappingRow {
  return {
    id: m.id,
    symbol: m.chartink_symbol,
    exchange: m.exchange,
    quantity: m.quantity,
    productType: m.product_type,
    isActive: true,
  }
}

/** Parses the `:connectionId` route param, which is `kind-id` (e.g.
 * "chartink-3" or "strategy-7") — see MaxHookIndex's Link targets. */
function parseConnectionId(raw: string | undefined): { kind: Kind; id: number } | null {
  if (!raw) return null
  const dashIndex = raw.indexOf('-')
  if (dashIndex === -1) return null
  const kind = raw.slice(0, dashIndex)
  const id = Number(raw.slice(dashIndex + 1))
  if ((kind !== 'strategy' && kind !== 'chartink') || Number.isNaN(id)) return null
  return { kind, id }
}

export default function ViewMaxHookConnection() {
  const { connectionId } = useParams<{ connectionId: string }>()
  const navigate = useNavigate()
  const parsed = parseConnectionId(connectionId)

  const [connection, setConnection] = useState<ConnectionDetail | null>(null)
  const [mappings, setMappings] = useState<MappingRow[]>([])
  const [loading, setLoading] = useState(true)
  const [toggling, setToggling] = useState(false)
  const [togglingMappingId, setTogglingMappingId] = useState<number | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [copiedField, setCopiedField] = useState<string | null>(null)
  const [hostConfig, setHostConfig] = useState<{
    host_server: string
    is_localhost: boolean
  } | null>(null)

  const fetchConnection = async () => {
    if (!parsed) return
    try {
      setLoading(true)
      if (parsed.kind === 'chartink') {
        const data = await chartinkApi.getStrategy(parsed.id)
        setConnection(normalizeChartink(data.strategy))
        setMappings((data.mappings || []).map(normalizeChartinkMapping))
      } else {
        const data = await strategyApi.getStrategy(parsed.id)
        setConnection(normalizeStrategy(data.strategy))
        setMappings((data.mappings || []).map(normalizeStrategyMapping))
      }
    } catch {
      showToast.error('Failed to load connection', 'maxhook')
      navigate('/maxhook')
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
      } catch {
        setHostConfig({
          host_server: window.location.origin,
          is_localhost:
            window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1',
        })
      }
    }
    fetchHostConfig()
  }, [])

  // biome-ignore lint/correctness/useExhaustiveDependencies: one-time fetch keyed on the route param, re-fetch only when it changes
  useEffect(() => {
    fetchConnection()
  }, [connectionId])

  const copyToClipboard = async (text: string, field: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedField(field)
      showToast.success('Copied to clipboard', 'clipboard')
      setTimeout(() => setCopiedField(null), 2000)
    } catch {
      showToast.error('Failed to copy', 'clipboard')
    }
  }

  const handleToggle = async () => {
    if (!connection || !parsed) return
    try {
      setToggling(true)
      const response =
        parsed.kind === 'chartink'
          ? await chartinkApi.toggleStrategy(connection.id)
          : await strategyApi.toggleStrategy(connection.id)
      if (response.status === 'success') {
        setConnection({ ...connection, isActive: response.data?.is_active ?? !connection.isActive })
        showToast.success(
          response.data?.is_active ? 'Connection activated' : 'Connection deactivated',
          'maxhook'
        )
      } else {
        showToast.error(response.message || 'Failed to toggle connection', 'maxhook')
      }
    } catch {
      showToast.error('Failed to toggle connection', 'maxhook')
    } finally {
      setToggling(false)
    }
  }

  const handleDelete = async () => {
    if (!connection || !parsed) return
    try {
      setDeleting(true)
      const response =
        parsed.kind === 'chartink'
          ? await chartinkApi.deleteStrategy(connection.id)
          : await strategyApi.deleteStrategy(connection.id)
      if (response.status === 'success') {
        showToast.success('Connection deleted', 'maxhook')
        navigate('/maxhook')
      } else {
        showToast.error(response.message || 'Failed to delete connection', 'maxhook')
      }
    } catch {
      showToast.error('Failed to delete connection', 'maxhook')
    } finally {
      setDeleting(false)
      setDeleteDialogOpen(false)
    }
  }

  const handleDeleteMapping = async (mappingId: number) => {
    if (!connection || !parsed) return
    try {
      const response =
        parsed.kind === 'chartink'
          ? await chartinkApi.deleteSymbolMapping(connection.id, mappingId)
          : await strategyApi.deleteSymbolMapping(connection.id, mappingId)
      if (response.status === 'success') {
        setMappings(mappings.filter((m) => m.id !== mappingId))
        showToast.success('Symbol mapping deleted', 'maxhook')
      } else {
        showToast.error(response.message || 'Failed to delete mapping', 'maxhook')
      }
    } catch {
      showToast.error('Failed to delete mapping', 'maxhook')
    }
  }

  // chartink-kind has no per-symbol toggle endpoint at all (see
  // normalizeChartinkMapping's comment) -- this is only ever called for
  // strategy-kind rows, whose Pause/Resume button is the only one rendered.
  const handleToggleMapping = async (mappingId: number) => {
    if (!connection) return
    setTogglingMappingId(mappingId)
    try {
      const response = await strategyApi.toggleSymbolMapping(connection.id, mappingId)
      if (response.status === 'success' && response.data) {
        const isActive = response.data.is_active
        setMappings(mappings.map((m) => (m.id === mappingId ? { ...m, isActive } : m)))
        showToast.success(isActive ? 'Symbol resumed' : 'Symbol paused', 'maxhook')
      } else {
        showToast.error(response.message || 'Failed to update symbol', 'maxhook')
      }
    } catch {
      showToast.error('Failed to update symbol', 'maxhook')
    } finally {
      setTogglingMappingId(null)
    }
  }

  const getTradingModeIcon = (mode: string | null) => {
    switch (mode) {
      case 'LONG':
        return <TrendingUp className="h-4 w-4 text-profit" />
      case 'SHORT':
        return <TrendingDown className="h-4 w-4 text-loss" />
      case 'BOTH':
        return <ArrowLeftRight className="h-4 w-4 text-info" />
      default:
        return null
    }
  }

  if (!parsed) {
    return null
  }

  if (loading) {
    return (
      <div className="container mx-auto py-6 space-y-6">
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-48" />
        <Skeleton className="h-64" />
      </div>
    )
  }

  if (!connection) {
    return null
  }

  const configureHref =
    parsed.kind === 'chartink'
      ? `/maxhook/${connection.id}/configure`
      : `/strategy/${connection.id}/configure`
  const baseUrl = hostConfig?.host_server || window.location.origin
  const webhookPath = parsed.kind === 'chartink' ? 'chartink/webhook' : 'strategy/webhook'
  const webhookUrl = `${baseUrl}/${webhookPath}/${connection.webhookId}`

  return (
    <div className="container mx-auto py-6 space-y-6">
      <Button variant="ghost" asChild>
        <Link to="/maxhook">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to MaxHook
        </Link>
      </Button>

      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-3">
            {connection.name}
            <Badge variant={connection.isActive ? 'default' : 'secondary'}>
              {connection.isActive ? 'Active' : 'Inactive'}
            </Badge>
          </h1>
          <p className="text-muted-foreground">
            {getSignalSourceLabel(connection.platform)} • Created{' '}
            {new Date(connection.createdAt).toLocaleDateString()}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant={connection.isActive ? 'outline' : 'default'}
            onClick={handleToggle}
            disabled={toggling}
          >
            <Power className="h-4 w-4 mr-2" />
            {toggling ? 'Updating...' : connection.isActive ? 'Deactivate' : 'Activate'}
          </Button>
          <Button variant="destructive" onClick={() => setDeleteDialogOpen(true)}>
            <Trash2 className="h-4 w-4 mr-2" />
            Delete
          </Button>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Connection Details</CardTitle>
            <CardDescription>Configuration and settings</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-sm text-muted-foreground">Status</p>
                <Badge variant={connection.isActive ? 'default' : 'secondary'} className="mt-1">
                  {connection.isActive ? 'Active' : 'Inactive'}
                </Badge>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Type</p>
                <Badge variant="outline" className="mt-1">
                  {connection.isIntraday ? 'Intraday' : 'Positional'}
                </Badge>
              </div>
              {connection.tradingMode && (
                <div>
                  <p className="text-sm text-muted-foreground">Trading Mode</p>
                  <div className="flex items-center gap-2 mt-1">
                    {getTradingModeIcon(connection.tradingMode)}
                    <span>{connection.tradingMode}</span>
                  </div>
                </div>
              )}
              <div>
                <p className="text-sm text-muted-foreground">Signal Provider</p>
                <p className="mt-1">{getSignalSourceLabel(connection.platform)}</p>
              </div>
              {connection.kind === 'chartink' && (
                <div>
                  <p className="text-sm text-muted-foreground">Exchanges</p>
                  <p className="mt-1">NSE, BSE only</p>
                </div>
              )}
            </div>

            {connection.isIntraday && connection.startTime && (
              <>
                <Separator />
                <div>
                  <p className="text-sm text-muted-foreground flex items-center gap-2 mb-2">
                    <Clock className="h-4 w-4" />
                    Trading Hours
                  </p>
                  <div className="grid grid-cols-3 gap-2 text-sm">
                    <div className="p-2 bg-muted rounded">
                      <p className="text-xs text-muted-foreground">Start</p>
                      <p className="font-mono">{connection.startTime}</p>
                    </div>
                    <div className="p-2 bg-muted rounded">
                      <p className="text-xs text-muted-foreground">End</p>
                      <p className="font-mono">{connection.endTime}</p>
                    </div>
                    <div className="p-2 bg-muted rounded">
                      <p className="text-xs text-muted-foreground">Square Off</p>
                      <p className="font-mono">{connection.squareoffTime}</p>
                    </div>
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Webhook className="h-5 w-5" />
              Webhook Configuration
            </CardTitle>
            <CardDescription>Use this URL to receive trading signals</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">Webhook URL</p>
              <div className="flex gap-2">
                <code className="flex-1 p-2 bg-muted rounded text-sm font-mono break-all">
                  {webhookUrl}
                </code>
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() => copyToClipboard(webhookUrl, 'url')}
                  aria-label={copiedField === 'url' ? 'Webhook URL copied' : 'Copy webhook URL'}
                >
                  {copiedField === 'url' ? (
                    <Check className="h-4 w-4 text-profit" />
                  ) : (
                    <Copy className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>

            {connection.kind === 'chartink' ? (
              <Alert>
                <Info className="h-4 w-4" />
                <AlertDescription>
                  <p className="font-medium mb-2">Chartink Setup:</p>
                  <ol className="list-decimal list-inside space-y-1 text-sm">
                    <li>Go to your Chartink screener settings</li>
                    <li>Add this webhook URL</li>
                    <li>Include BUY/SELL/SHORT/COVER in alert name</li>
                    <li>Save and enable alerts</li>
                  </ol>
                </AlertDescription>
              </Alert>
            ) : (
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground flex items-center gap-2">
                  <Code className="h-4 w-4" />
                  Alert Message Format
                </p>
                <pre className="p-3 bg-muted rounded text-xs font-mono overflow-x-auto">
                  {`{
  "signal": "BUY"
}`}
                </pre>
                <p className="text-xs text-muted-foreground">
                  Use BUY, SELL, EXIT, SHORT, or COVER for the signal field.
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Alert>
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>Important Notes</AlertTitle>
        <AlertDescription>
          <ul className="list-disc list-inside mt-2 space-y-1 text-sm">
            <li>
              Signals are processed only when the connection is <strong>active</strong>
            </li>
            {connection.isIntraday && (
              <li>
                Signals are processed only during trading hours ({connection.startTime} -{' '}
                {connection.endTime})
              </li>
            )}
            <li>Symbol must be configured in the mappings below to receive orders</li>
            <li>
              Identical signals received within a few seconds of each other are{' '}
              <strong>suppressed</strong> to prevent a retry from placing a duplicate order
            </li>
            <li>
              <strong>Treat the webhook URL like a password</strong> — anyone who has it can
              send signals to this connection
            </li>
            {connection.kind === 'chartink' && (
              <>
                <li>Only NSE and BSE exchanges are supported</li>
                <li>Only MIS and CNC product types are supported</li>
                <li>
                  The scan name must contain exactly one of BUY / SELL / SHORT / COVER. Names
                  with conflicting keywords (e.g. &quot;SELL TO COVER&quot;) are rejected rather
                  than guessed
                </li>
              </>
            )}
          </ul>
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader>
          <CardTitle>Signal Delivery Log</CardTitle>
          <CardDescription>
            Every signal received by this connection, and what happened to it. Expand a row to
            see the step-by-step trace.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <DeliveryLogPanel
            strategyId={connection.kind === 'strategy' ? connection.id : undefined}
            webhookId={connection.webhookId}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Symbol Mappings</CardTitle>
            <CardDescription>
              Symbols configured for this connection ({mappings.length} total)
            </CardDescription>
          </div>
          <Button asChild>
            <Link to={configureHref}>
              <Settings className="h-4 w-4 mr-2" />
              Configure Symbols
            </Link>
          </Button>
        </CardHeader>
        <CardContent>
          {mappings.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <p>No symbols configured yet.</p>
              <Button variant="link" asChild>
                <Link to={configureHref}>Add your first symbol</Link>
              </Button>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Exchange</TableHead>
                  <TableHead className="text-right">Quantity</TableHead>
                  <TableHead>Product</TableHead>
                  <TableHead className="w-28" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {mappings.map((mapping) => (
                  <TableRow key={mapping.id} className={mapping.isActive ? '' : 'opacity-60'}>
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2">
                        {mapping.symbol}
                        {!mapping.isActive && (
                          <Badge variant="secondary" className="text-[10px]">
                            Paused
                          </Badge>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>{mapping.exchange}</TableCell>
                    <TableCell className="text-right">{mapping.quantity}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{mapping.productType}</Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-0.5">
                        {/* chartink-kind mappings have no per-symbol
                        toggle -- see normalizeChartinkMapping's comment --
                        so this button only renders for strategy-kind
                        connections, matching what handleToggleMapping
                        actually supports. */}
                        {parsed?.kind !== 'chartink' && (
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleToggleMapping(mapping.id)}
                            disabled={togglingMappingId === mapping.id}
                            title={mapping.isActive ? 'Pause' : 'Resume'}
                            aria-label={
                              mapping.isActive
                                ? `Pause ${mapping.symbol}`
                                : `Resume ${mapping.symbol}`
                            }
                          >
                            {mapping.isActive ? (
                              <Pause className="h-4 w-4" />
                            ) : (
                              <Play className="h-4 w-4" />
                            )}
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="icon"
                          asChild
                          title="Edit"
                          aria-label={`Edit ${mapping.symbol}`}
                        >
                          {/* Jumps straight into ConfigureSymbols scrolled
                          to and highlighting this exact rule, instead of
                          landing at the top of a page the user then has to
                          scan through -- see ConfigureSymbols' handling of
                          the highlight query param. */}
                          <Link to={`${configureHref}?highlight=${mapping.id}`}>
                            <Pencil className="h-4 w-4" />
                          </Link>
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="text-loss hover:text-loss hover:bg-loss/10"
                          onClick={() => handleDeleteMapping(mapping.id)}
                          aria-label={`Delete ${mapping.symbol}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Connection</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete "{connection.name}"? This action cannot be undone. All
              symbol mappings will also be deleted.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting ? 'Deleting...' : 'Delete Connection'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
