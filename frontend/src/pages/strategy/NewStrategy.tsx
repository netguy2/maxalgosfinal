import { ArrowLeft, Code2, LineChart, Webhook, Workflow } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

// Every engine that can create a strategy. Each has its own dedicated
// creation flow — this page is purely a picker. Webhook connections
// (TradingView, Chartink, and any other external signal source) are
// created via MaxHook, which owns the simplified create form and the
// provider-specific setup instructions.
const ENGINES = [
  {
    id: 'webhook',
    label: 'Webhook (MaxHook)',
    description: 'Receive signals from TradingView, Chartink, or any external tool',
    icon: Webhook,
    href: '/maxhook/new',
  },
  {
    id: 'visual-builder',
    label: 'Visual Builder',
    description: 'Build multi-leg option structures visually',
    icon: LineChart,
    href: '/visual-builder',
  },
  {
    id: 'python',
    label: 'Python',
    description: 'Full control with a Python script',
    icon: Code2,
    href: '/python/new',
  },
  {
    id: 'flow',
    label: 'Automation Studio',
    description: 'No-code node-based automation',
    icon: Workflow,
    href: '/flow',
  },
] as const

export default function NewStrategy() {
  const navigate = useNavigate()

  return (
    <div className="container mx-auto py-6 max-w-2xl space-y-6">
      <Button variant="ghost" asChild>
        <Link to="/strategy">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Strategies
        </Link>
      </Button>

      <div>
        <h1 className="text-2xl font-bold tracking-tight">Create New Strategy</h1>
        <p className="text-muted-foreground">Choose how you want to build this strategy.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {ENGINES.map((engine) => (
          <Card
            key={engine.id}
            className="cursor-pointer transition-colors hover:border-primary/40"
            onClick={() => navigate(engine.href)}
          >
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <engine.icon className="h-5 w-5 text-primary" />
                {engine.label}
              </CardTitle>
              <CardDescription>{engine.description}</CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="outline" size="sm" className="w-full" asChild>
                <Link to={engine.href} onClick={(e) => e.stopPropagation()}>
                  Get started
                </Link>
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
