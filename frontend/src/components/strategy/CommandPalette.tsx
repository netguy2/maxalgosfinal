import {
  Activity,
  BarChart3,
  Code2,
  Copy,
  ExternalLink,
  Layers,
  Play,
  Plus,
  RefreshCw,
  Search,
  Settings,
  Sparkles,
  Square,
  Webhook,
  Zap,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import type { UnifiedRow } from './UnifiedStrategyCard'

interface Props {
  open: boolean
  onClose: () => void
  rows: UnifiedRow[]
  onInspect: (row: UnifiedRow) => void
  onDeploy: (row: UnifiedRow) => void
  onBacktest: (row: UnifiedRow) => void
}

export function CommandPalette({
  open,
  onClose,
  rows,
  onInspect,
  onDeploy,
  onBacktest,
}: Props) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        if (open) onClose()
        else {
          /* handled externally or by parent */
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose])

  const filtered = rows.filter((r) =>
    r.data.name.toLowerCase().includes(query.toLowerCase())
  )

  const quickNav = [
    { label: 'Create New Strategy', icon: Plus, path: '/strategy/new' },
    { label: 'AI Strategy Wizard', icon: Sparkles, path: '/strategy/wizard' },
    { label: 'Add Python Script', icon: Code2, path: '/python/new' },
    { label: 'Historical Backtest Engine', icon: BarChart3, path: '/backtest' },
    { label: 'Browse Marketplace', icon: Layers, path: '/marketplace' },
  ]

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-xl p-0 overflow-hidden gap-0 border-border bg-card">
        <DialogHeader className="p-4 border-b border-border bg-muted/30">
          <div className="flex items-center gap-2">
            <Search className="h-4 w-4 text-muted-foreground shrink-0" />
            <Input
              placeholder="Type a command or strategy name... (Ctrl + K)"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="border-none bg-transparent focus-visible:ring-0 focus-visible:ring-offset-0 text-sm h-7"
              autoFocus
            />
            <kbd className="pointer-events-none inline-flex h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground opacity-100">
              ESC
            </kbd>
          </div>
        </DialogHeader>

        <div className="max-h-96 overflow-y-auto p-2 divide-y divide-border/40">
          {/* Quick Navigation Shortcuts */}
          {!query && (
            <div className="p-2 space-y-1">
              <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground px-2">
                Quick Shortcuts
              </span>
              {quickNav.map((item) => {
                const Icon = item.icon
                return (
                  <button
                    key={item.label}
                    type="button"
                    onClick={() => {
                      onClose()
                      navigate(item.path)
                    }}
                    className="w-full flex items-center justify-between p-2 rounded-lg text-xs hover:bg-muted text-left transition-colors"
                  >
                    <span className="flex items-center gap-2 text-foreground font-semibold">
                      <Icon className="h-3.5 w-3.5 text-primary" />
                      {item.label}
                    </span>
                    <span className="text-[10px] text-muted-foreground font-mono">Jump →</span>
                  </button>
                )
              })}
            </div>
          )}

          {/* Strategy Search Matches */}
          <div className="p-2 space-y-1">
            <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground px-2">
              Strategies ({filtered.length})
            </span>
            {filtered.length === 0 ? (
              <p className="p-4 text-xs text-muted-foreground text-center">
                No matching strategies found.
              </p>
            ) : (
              filtered.slice(0, 8).map((row) => (
                <div
                  key={`${row.kind}-${row.data.id}`}
                  className="flex items-center justify-between p-2 rounded-lg text-xs hover:bg-muted text-left transition-colors group"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="p-1 rounded bg-muted text-foreground font-bold text-[10px] uppercase">
                      {row.kind}
                    </span>
                    <span className="font-bold text-foreground truncate">{row.data.name}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 text-[10px] px-2"
                      onClick={() => {
                        onClose()
                        onInspect(row)
                      }}
                    >
                      Inspect
                    </Button>
                    {row.kind === 'webhook' && (
                      <Button
                        variant="default"
                        size="sm"
                        className="h-6 text-[10px] px-2"
                        onClick={() => {
                          onClose()
                          onDeploy(row)
                        }}
                      >
                        Deploy
                      </Button>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
