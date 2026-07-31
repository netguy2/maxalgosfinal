import { BarChart3, Check, Code2, Copy, FileSpreadsheet, LineChart, ScanSearch, Terminal, Webhook } from 'lucide-react'
import { useState } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { showToast } from '@/utils/toast'

// Any platform that can send an HTTP POST works. These are the ones with
// documented integrations; "Others" covers everything else via raw webhook.
const SUPPORTED_PLATFORMS = [
  { name: 'TradingView', icon: BarChart3, note: 'Pine Script alerts → webhook URL (JSON in alert message).' },
  { name: 'ChartInk', icon: ScanSearch, note: 'Screener alerts POST the scan result to the webhook.' },
  { name: 'GoCharting', icon: LineChart, note: 'Alert webhooks with a JSON payload.' },
  { name: 'Amibroker', icon: Code2, note: 'AFL InternetPostRequest to the webhook URL.' },
  { name: 'Python', icon: Terminal, note: 'requests.post(url, json=payload) from any script.' },
  { name: 'Excel / Sheets', icon: FileSpreadsheet, note: 'WEBSERVICE / Apps Script POST to the webhook.' },
  { name: 'MetaTrader 4/5', icon: LineChart, note: 'WebRequest() from an EA to the webhook URL.' },
  { name: 'Others / REST', icon: Webhook, note: 'Any client that can send an HTTP POST request.' },
]

const ACTION_TOKENS = [
  { token: 'BUY', className: 'bg-profit/15 text-profit border-profit/30', desc: 'Triggers BUY leg mappings' },
  { token: 'SELL', className: 'bg-loss/15 text-loss border-loss/30', desc: 'Triggers SELL leg mappings' },
  { token: 'SHORT', className: 'bg-sell/15 text-sell border-sell/30', desc: 'Opens a SHORT position' },
  { token: 'COVER', className: 'bg-buy/15 text-buy border-buy/30', desc: 'Covers / closes a position' },
]

const PAYLOAD_EXAMPLE = `{
  "apikey": "YOUR_API_KEY",
  "strategy": "my-strategy",
  "action": "BUY",
  "symbol": "SBIN",
  "exchange": "NSE",
  "product": "MIS",
  "quantity": 1
}`

const TRADINGVIEW_EXAMPLE = `{
  "apikey": "YOUR_API_KEY",
  "strategy": "my-strategy",
  "action": "{{strategy.order.action}}",
  "symbol": "{{ticker}}",
  "exchange": "NSE",
  "product": "MIS",
  "quantity": "{{strategy.order.contracts}}"
}`

function CodeBlock({ code, label }: { code: string; label: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      showToast.success('Copied to clipboard', 'clipboard')
      setTimeout(() => setCopied(false), 2000)
    } catch {
      showToast.error('Failed to copy', 'clipboard')
    }
  }
  return (
    <div className="relative">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs font-semibold text-muted-foreground">{label}</span>
        <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={copy}>
          {copied ? <Check className="h-3 w-3 mr-1 text-profit" /> : <Copy className="h-3 w-3 mr-1" />}
          Copy
        </Button>
      </div>
      <pre className="rounded-md border border-border bg-muted/40 p-3 text-xs overflow-x-auto scrollbar-thin font-mono">
        {code}
      </pre>
    </div>
  )
}

/**
 * Webhook integration reference — replaces the old standalone Platforms page.
 * Since a strategy is configured to accept signals from any platform, this
 * documents the supported senders and the JSON payload format they post.
 */
export function WebhookGuide() {
  return (
    <div className="space-y-6">
      <Alert>
        <Webhook className="h-4 w-4" />
        <AlertTitle>Signals can come from any platform</AlertTitle>
        <AlertDescription className="leading-relaxed">
          A strategy exposes one webhook URL (see the strategy's detail page). Any tool that can
          send an HTTP POST — TradingView, ChartInk, Amibroker, Python, Excel, MetaTrader, or your
          own code — can trigger it using the payload format below. No per-platform setup page is
          needed.
        </AlertDescription>
      </Alert>

      {/* Supported platforms */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Supported Platforms</CardTitle>
          <CardDescription>Documented senders — everything else works via raw REST.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {SUPPORTED_PLATFORMS.map((p) => (
              <div key={p.name} className="flex items-start gap-3 rounded-lg border border-border p-3">
                <div className="p-2 rounded-md bg-primary/10 text-primary shrink-0">
                  <p.icon className="h-4 w-4" />
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-semibold">{p.name}</p>
                  <p className="text-xs text-muted-foreground leading-snug">{p.note}</p>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Action tokens */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Action Tokens</CardTitle>
          <CardDescription>The <code className="text-xs">action</code> field drives which mappings execute.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {ACTION_TOKENS.map((a) => (
              <div key={a.token} className="space-y-1">
                <Badge variant="outline" className={`font-bold ${a.className}`}>{a.token}</Badge>
                <p className="text-xs text-muted-foreground">{a.desc}</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Payload format */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Webhook Payload Format</CardTitle>
          <CardDescription>POST JSON to your strategy's webhook URL.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <CodeBlock label="Standard JSON payload" code={PAYLOAD_EXAMPLE} />
          <CodeBlock label="TradingView alert message (uses placeholders)" code={TRADINGVIEW_EXAMPLE} />
        </CardContent>
      </Card>
    </div>
  )
}
