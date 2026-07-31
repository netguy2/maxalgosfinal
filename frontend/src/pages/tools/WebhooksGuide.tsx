import { ArrowLeft } from 'lucide-react'
import { Link } from 'react-router-dom'
import { WebhookGuide } from '@/components/strategy-builder/WebhookGuide'
import { Button } from '@/components/ui/button'

/**
 * Webhook integration documentation — supported platforms, action tokens,
 * and payload format. Lives under Tools since it's reference documentation,
 * not a strategy-management action.
 */
export default function WebhooksGuide() {
  return (
    <div className="container mx-auto py-6 space-y-6 max-w-5xl px-4 sm:px-6">
      <Button variant="ghost" size="sm" className="w-fit" asChild>
        <Link to="/strategy">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Strategies
        </Link>
      </Button>

      <div>
        <h1 className="text-2xl font-bold tracking-tight">Webhooks Guide</h1>
        <p className="text-muted-foreground">
          Supported platforms, action tokens, and payload format for webhook strategies.
        </p>
      </div>

      <WebhookGuide />
    </div>
  )
}
