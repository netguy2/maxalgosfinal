import {
  Activity,
  ArrowRight,
  ClipboardList,
  Clock,
  FileText,
  FlaskConical,
  HeartPulse,
  Shield,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export default function LogsIndex() {
  const logCards = [
    {
      title: 'Live Logs',
      description: 'View real-time API order logs with request and response data',
      icon: ClipboardList,
      href: '/logs/live',
      color: 'bg-info',
      countLabel: 'orders',
    },
    {
      title: 'Sandbox Logs',
      description: 'Track and test your trading strategies before going live',
      icon: FlaskConical,
      href: '/logs/sandbox',
      color: 'bg-cat-2',
      countLabel: 'testing',
    },
    {
      title: 'Latency Monitor',
      description: 'Track order execution latency and performance metrics',
      icon: Clock,
      href: '/logs/latency',
      color: 'bg-cat-6',
      countLabel: 'monitoring',
    },
    {
      title: 'Traffic Monitor',
      description: 'Monitor HTTP requests, endpoints, and response times',
      icon: Activity,
      href: '/logs/traffic',
      color: 'bg-cat-3',
      countLabel: 'monitoring',
    },
    {
      title: 'Security Logs',
      description: 'Monitor security events, banned IPs, and threat activity',
      icon: Shield,
      href: '/logs/security',
      color: 'bg-loss',
      countLabel: 'security',
    },
    {
      title: 'Health Monitor',
      description: 'Track system health, file descriptors, memory, and connections',
      icon: HeartPulse,
      href: '/health',
      color: 'bg-profit',
      countLabel: 'health',
    },
  ]

  return (
    <PageContainer>
      {/* Header */}
      <PageHeader
        title="Logs & Monitoring"
        icon={<FileText />}
        actions={
          <p className="text-muted-foreground mt-1">
            Access trading logs, monitor system performance, and track security events
          </p>
        }
      />

      {/* Log Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {logCards.map((card) => (
          <Link key={card.href} to={card.href}>
            <Card className="h-full hover:shadow-lg transition-shadow cursor-pointer group">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div
                    className={`w-10 h-10 rounded-lg ${card.color} flex items-center justify-center`}
                  >
                    <card.icon className="h-5 w-5 text-white" />
                  </div>
                  <Badge variant="secondary">{card.countLabel}</Badge>
                </div>
                <CardTitle className="flex items-center gap-2 group-hover:text-primary transition-colors">
                  {card.title}
                  <ArrowRight className="h-4 w-4 opacity-0 group-hover:opacity-100 transition-opacity" />
                </CardTitle>
                <CardDescription>{card.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="text-sm text-muted-foreground">
                  Click to view {card.title.toLowerCase()}
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </PageContainer>
  )
}
