import {
  Activity,
  AlertTriangle,
  BarChart3,
  CheckCircle,
  Download,
  Eye,
  Filter,
  Users,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { DocsLink } from '@/components/DocsLink'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { JsonEditor } from '@/components/ui/json-editor'
import { Label } from '@/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface ApiRequest {
  timestamp: string
  api_type: string
  source: string
  symbol?: string
  quantity?: number
  position_size?: number
  orderid?: string
  exchange?: string
  action?: string
  request_data: Record<string, unknown>
  response_data?: Record<string, unknown>
  analysis: {
    issues?: boolean | string[]
    error?: string
    error_type?: string
    warnings?: string[]
  }
}

interface Stats {
  total_requests: number
  issues: {
    total: number
  }
  symbols: string[]
  sources: string[]
}

interface AnalyzerData {
  requests: ApiRequest[]
  stats: Stats
}

const EXCHANGE_COLORS: Record<string, string> = {
  NSE: 'bg-cat-3/10 text-cat-3 border-cat-3/30',
  NFO: 'bg-cat-2/10 text-cat-2 border-cat-2/30',
  CDS: 'bg-info/10 text-info border-info/30',
  BSE: 'bg-muted-foreground/10 text-muted-foreground border-muted-foreground/30',
  BFO: 'bg-warning/10 text-warning border-warning/30',
  BCD: 'bg-loss/10 text-loss border-loss/30',
  MCX: 'bg-primary/10 text-primary border-primary/30',
  NCDEX: 'bg-profit/10 text-profit border-profit/30',
  NCO: 'bg-profit/10 text-profit border-profit/30',
  NSE_INDEX: 'bg-cat-3/10 text-cat-3 border-cat-3/30',
  BSE_INDEX: 'bg-muted-foreground/10 text-muted-foreground border-muted-foreground/30',
  GLOBAL_INDEX: 'bg-info/10 text-info border-info/30',
}

export default function Analyzer() {
  const [data, setData] = useState<AnalyzerData | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [selectedRequest, setSelectedRequest] = useState<ApiRequest | null>(null)
  const [showDetailsDialog, setShowDetailsDialog] = useState(false)

  // biome-ignore lint/correctness/useExhaustiveDependencies: one-time data load on mount; subsequent fetches are triggered explicitly by the filter form
  useEffect(() => {
    fetchData()
  }, [])

  const fetchData = async (start?: string, end?: string) => {
    setIsLoading(true)
    try {
      const params = new URLSearchParams()
      if (start) params.append('start_date', start)
      if (end) params.append('end_date', end)

      const url = params.toString() ? `/analyzer/api/data?${params}` : '/analyzer/api/data'

      const response = await fetch(url, {
        credentials: 'include',
      })

      if (response.ok) {
        const result = await response.json()
        if (result.status === 'success') {
          setData(result.data)
        }
      }
    } catch (_error) {
    } finally {
      setIsLoading(false)
    }
  }

  const handleFilter = (e: React.FormEvent) => {
    e.preventDefault()
    fetchData(startDate, endDate)
  }

  const handleExport = () => {
    const params = new URLSearchParams()
    if (startDate) params.append('start_date', startDate)
    if (endDate) params.append('end_date', endDate)

    const url = params.toString() ? `/analyzer/export?${params}` : '/analyzer/export'
    window.location.href = url
  }

  const viewDetails = (request: ApiRequest) => {
    setSelectedRequest(request)
    setShowDetailsDialog(true)
  }

  const getRequestDetails = (request: ApiRequest): string => {
    if (request.api_type === 'cancelorder') {
      return `OrderID: ${request.orderid}`
    }

    let details = request.symbol || ''
    if (request.quantity) {
      details += ` (${request.quantity})`
    }
    if (request.api_type === 'placesmartorder' && request.position_size) {
      details += ` [Size: ${request.position_size}]`
    }
    return details
  }

  // Clean request data for display (remove apikey)
  const cleanRequestData = (data: Record<string, unknown>): Record<string, unknown> => {
    const cleaned = { ...data }
    delete cleaned.apikey
    return cleaned
  }

  if (isLoading) {
    return (
      <div className="container mx-auto py-8 px-4 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  const stats = data?.stats || { total_requests: 0, issues: { total: 0 }, symbols: [], sources: [] }
  const requests = data?.requests || []

  return (
    <PageContainer spacing="none">
      {/* Header */}
      <PageHeader
        title="Sandbox Request Monitor"
        description="Review and validate your sandbox API requests before going live"
        actions=<DocsLink page="analyzer" />
      />

      {/* Date Filter */}
      <Card className="mb-6">
        <CardHeader className="pb-3">
          <CardTitle className="text-lg flex items-center gap-2">
            <Filter className="h-4 w-4" />
            Filters
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleFilter} className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
            <div className="space-y-2">
              <Label htmlFor="start_date" className="text-sm font-medium">
                Start Date
              </Label>
              <Input
                id="start_date"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="date-input-styled"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="end_date" className="text-sm font-medium">
                End Date
              </Label>
              <Input
                id="end_date"
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="date-input-styled"
              />
            </div>
            <div className="flex gap-2 pt-6">
              <Button type="submit">
                <Filter className="h-4 w-4 mr-2" />
                Filter
              </Button>
              <Button type="button" variant="secondary" onClick={handleExport}>
                <Download className="h-4 w-4 mr-2" />
                Export CSV
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Activity className="h-4 w-4" />
              Total Requests
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-primary">{stats.total_requests}</div>
            <Badge className="mt-1">Last 24 hours</Badge>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" />
              Issues Found
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-warning">{stats.issues.total}</div>
            <Badge variant="secondary" className="mt-1">
              Needs Attention
            </Badge>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <BarChart3 className="h-4 w-4" />
              Unique Symbols
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{stats.symbols.length}</div>
            <Badge variant="outline" className="mt-1">
              Tracked
            </Badge>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Users className="h-4 w-4" />
              Active Sources
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{stats.sources.length}</div>
            <Badge variant="outline" className="mt-1">
              Connected
            </Badge>
          </CardContent>
        </Card>
      </div>

      {/* Requests Table */}
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Timestamp</TableHead>
                  <TableHead>API Type</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Details</TableHead>
                  <TableHead>Exchange</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>View</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {requests.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="text-center py-8 text-muted-foreground">
                      No requests found
                    </TableCell>
                  </TableRow>
                ) : (
                  requests.map((request, index) => (
                    <TableRow key={index} className="hover:bg-muted/50">
                      <TableCell className="text-sm">{request.timestamp}</TableCell>
                      <TableCell>
                        <Badge variant="default">{request.api_type}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary" className="truncate max-w-[120px]">
                          {request.source}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-medium">{getRequestDetails(request)}</TableCell>
                      <TableCell>
                        {request.exchange && (
                          <Badge
                            className={EXCHANGE_COLORS[request.exchange] || ''}
                            variant="outline"
                          >
                            {request.exchange}
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        {request.action && (
                          <Badge variant={request.action === 'BUY' ? 'default' : 'destructive'}>
                            {request.action}
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        {request.analysis.issues ? (
                          <Badge
                            variant="secondary"
                            className="bg-warning/10 text-warning border-warning/30"
                          >
                            <AlertTriangle className="h-3 w-3 mr-1" />
                            Error
                          </Badge>
                        ) : (
                          <Badge
                            variant="secondary"
                            className="bg-profit/10 text-profit border-profit/30"
                          >
                            <CheckCircle className="h-3 w-3 mr-1" />
                            Success
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <Button size="sm" onClick={() => viewDetails(request)}>
                          <Eye className="h-4 w-4 mr-1" />
                          View
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Request Details Dialog */}
      <Dialog open={showDetailsDialog} onOpenChange={setShowDetailsDialog}>
        <DialogContent size="full" className="p-4">
          <DialogHeader>
            <DialogTitle>Request Details</DialogTitle>
          </DialogHeader>
          {selectedRequest &&
            (() => {
              const requestJson = JSON.stringify(
                cleanRequestData(selectedRequest.request_data),
                null,
                2
              )
              const responseJson = JSON.stringify(
                selectedRequest.response_data || selectedRequest.analysis,
                null,
                2
              )
              const requestLines = requestJson.split('\n').length
              const responseLines = responseJson.split('\n').length
              const maxLines = Math.max(requestLines, responseLines)
              // Allow up to 70vh height
              const height = Math.min(Math.max(maxLines * 20 + 24, 200), window.innerHeight * 0.7)

              return (
                <DialogBody className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <div className="min-w-0 overflow-hidden">
                    <h4 className="font-semibold mb-2">Request Data</h4>
                    <div className="rounded-lg border bg-card/50 overflow-auto" style={{ height }}>
                      <JsonEditor value={requestJson} readOnly={true} lineWrapping={false} />
                    </div>
                  </div>
                  <div className="min-w-0 overflow-hidden">
                    <h4 className="font-semibold mb-2">Response Data</h4>
                    <div className="rounded-lg border bg-card/50 overflow-auto" style={{ height }}>
                      <JsonEditor value={responseJson} readOnly={true} lineWrapping={false} />
                    </div>
                  </div>
                </DialogBody>
              )
            })()}
        </DialogContent>
      </Dialog>
    </PageContainer>
  )
}
