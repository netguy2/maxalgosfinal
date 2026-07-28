/**
 * Basket Close Node
 * Squares off only a caller-specified list of positions (a "basket"),
 * unlike Close Positions which is broker-wide with no selectivity.
 */

import { Handle, Position } from '@xyflow/react'
import { Target } from 'lucide-react'
import { memo } from 'react'
import { cn } from '@/lib/utils'
import type { BasketCloseNodeData } from '@/types/flow'

interface BasketCloseNodeProps {
  data: BasketCloseNodeData
  selected?: boolean
}

export const BasketCloseNode = memo(({ data, selected }: BasketCloseNodeProps) => {
  const symbolCount = (data.symbols || '')
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean).length

  return (
    <div className={cn('workflow-node node-action min-w-[110px]', selected && 'selected')}>
      <Handle type="target" position={Position.Top} className="!top-0 !-translate-y-1/2" />
      <div className="p-2">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="node-icon flex h-5 w-5 items-center justify-center rounded bg-sell/20 text-sell">
            <Target className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Basket Close</div>
            <div className="text-[9px] text-muted-foreground">Square off a basket</div>
          </div>
        </div>
        {symbolCount > 0 ? (
          <div className="rounded bg-sell/10 px-1.5 py-1 text-center">
            <span className="text-[9px] text-sell">
              Closes {symbolCount} position{symbolCount === 1 ? '' : 's'}
            </span>
          </div>
        ) : (
          <div className="rounded bg-muted/50 px-1.5 py-1 text-center">
            <span className="text-[9px] text-muted-foreground">No symbols configured</span>
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bottom-0 !translate-y-1/2" />
    </div>
  )
})

BasketCloseNode.displayName = 'BasketCloseNode'
