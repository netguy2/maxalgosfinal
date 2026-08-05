import { ArrowLeft } from 'lucide-react'
import { Link } from 'react-router-dom'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
import { WebhookGuide } from '@/components/strategy-builder/WebhookGuide'
import { Button } from '@/components/ui/button'

/**
 * Webhook integration documentation — supported platforms, action tokens,
 * and payload format. Lives under Tools since it's reference documentation,
 * not a strategy-management action.
 */
export default function WebhooksGuide() {
  return (
    <PageContainer>
      <Button variant="ghost" size="sm" className="w-fit" asChild>
        <Link to="/strategy">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Strategies
        </Link>
      </Button>

      <PageHeader
        title="Webhooks Guide"
        description="Supported platforms, action tokens, and payload format for webhook strategies."
      />

      <WebhookGuide />
    </PageContainer>
  )
}
